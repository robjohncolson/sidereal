"""SQLite persistence for symbolic interpretation records."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Iterable, Iterator, Sequence

from .schema import (
    SEED_SCHEMA_VERSION,
    SELF_ASPECT_BODIES,
    InterpretationEntry,
    expected_entry_ids,
)


DATABASE_SCHEMA_VERSION = 2


class InterpretationStoreError(RuntimeError):
    """Base class for interpretation store failures."""


class StoreNotInitializedError(InterpretationStoreError):
    """Raised when a data operation is attempted before ``initialize``."""


class SeedImportError(InterpretationStoreError):
    """Raised when a seed file is invalid or conflicts at the same version."""


@dataclass(frozen=True, slots=True)
class ImportResult:
    files: int
    records: int
    inserted: int
    updated: int
    unchanged: int
    skipped: int

    def to_dict(self) -> dict[str, int]:
        return {
            "files": self.files,
            "records": self.records,
            "inserted": self.inserted,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
        }


@dataclass(frozen=True, slots=True)
class InventoryAudit:
    expected: int
    ready: int
    stub: int
    missing: int
    ready_ids: tuple[str, ...]
    stub_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]

    @property
    def has_gaps(self) -> bool:
        return bool(self.stub_ids or self.missing_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "expected": self.expected,
            "ready": self.ready,
            "stub": self.stub,
            "missing": self.missing,
            "ready_ids": list(self.ready_ids),
            "stub_ids": list(self.stub_ids),
            "missing_ids": list(self.missing_ids),
        }


def _entry_table_sql(table_name: str, *, if_not_exists: bool = False) -> str:
    create_clause = "IF NOT EXISTS " if if_not_exists else ""
    same_body_allowlist = ", ".join(f"'{body}'" for body in SELF_ASPECT_BODIES)
    return f"""
CREATE TABLE {create_clause}{table_name} (
    id TEXT PRIMARY KEY,
    entry_type TEXT NOT NULL,
    planet TEXT,
    sign TEXT,
    house INTEGER CHECK (house IS NULL OR house BETWEEN 1 AND 12),
    angle TEXT,
    body_a TEXT,
    body_b TEXT,
    aspect_type TEXT,
    pattern_type TEXT,
    title TEXT NOT NULL,
    keywords_json TEXT NOT NULL,
    summary TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    shadow TEXT NOT NULL DEFAULT '',
    growth TEXT NOT NULL DEFAULT '',
    blend_note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    license TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('stub', 'ready', 'user')),
    version INTEGER NOT NULL CHECK (version >= 1),
    updated TEXT NOT NULL,
    CHECK (
        body_a IS NULL
        OR body_b IS NULL
        OR body_a < body_b
        OR (
            entry_type = 'aspect'
            AND body_a = body_b
            AND body_a IN ({same_body_allowlist})
        )
    )
);
"""


_INDEX_SQL_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS interpretation_entries_type_idx "
    "ON interpretation_entries(entry_type)",
    "CREATE INDEX IF NOT EXISTS interpretation_entries_status_idx "
    "ON interpretation_entries(status)",
)
_META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS interpretation_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
_SCHEMA_SQL = "\n".join(
    (
        _entry_table_sql("interpretation_entries", if_not_exists=True),
        *(statement + ";" for statement in _INDEX_SQL_STATEMENTS),
        _META_TABLE_SQL,
    )
)

_ENTRY_COLUMNS = (
    "id",
    "entry_type",
    "planet",
    "sign",
    "house",
    "angle",
    "body_a",
    "body_b",
    "aspect_type",
    "pattern_type",
    "title",
    "keywords_json",
    "summary",
    "body",
    "shadow",
    "growth",
    "blend_note",
    "source",
    "license",
    "status",
    "version",
    "updated",
)


class InterpretationStore:
    """Small, explicit SQLite store with atomic deterministic seed imports."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "InterpretationStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _connect(self, *, create_parent: bool = False) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        if self.path != ":memory:":
            path = Path(self.path)
            if create_parent:
                path.parent.mkdir(parents=True, exist_ok=True)
            elif not path.exists():
                raise StoreNotInitializedError(
                    f"interpretation database does not exist: {path}; run 'db init' first"
                )
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        self._connection = connection
        return connection

    def initialize(self) -> None:
        connection = self._connect(create_parent=True)
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        owned_tables = {"interpretation_entries", "interpretation_meta"}
        if current_version not in (0, 1, DATABASE_SCHEMA_VERSION):
            raise StoreNotInitializedError(
                f"refusing to overwrite interpretation schema version {current_version}; "
                f"this build supports version {DATABASE_SCHEMA_VERSION}"
            )
        if current_version == 0 and tables & owned_tables:
            raise StoreNotInitializedError(
                "interpretation tables exist without a supported schema version; "
                "an explicit migration is required"
            )
        if current_version == 1:
            self._assert_schema_version(connection, 1)
            self._migrate_v1_to_v2(connection)
            self._assert_current_schema(connection)
            return
        if current_version == DATABASE_SCHEMA_VERSION:
            self._assert_current_schema(connection)
            # Retain idempotent index creation, but never rewrite a versioned
            # database merely because `db init` was invoked again.
            with connection:
                connection.executescript(_SCHEMA_SQL)
            return
        with connection:
            connection.executescript(_SCHEMA_SQL)
            connection.execute(
                "INSERT INTO interpretation_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(DATABASE_SCHEMA_VERSION),),
            )
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")

    def _require_schema(self) -> sqlite3.Connection:
        connection = self._connect()
        self._assert_current_schema(connection)
        return connection

    @staticmethod
    def _assert_current_schema(connection: sqlite3.Connection) -> None:
        InterpretationStore._assert_schema_version(
            connection, DATABASE_SCHEMA_VERSION
        )

    @staticmethod
    def _assert_schema_version(
        connection: sqlite3.Connection, expected_version: int
    ) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != expected_version:
            migration_hint = (
                "; run 'python -m sidereal db init --db PATH' to migrate"
                if version == 1 and expected_version == DATABASE_SCHEMA_VERSION
                else ""
            )
            raise StoreNotInitializedError(
                f"unsupported interpretation schema version {version}; "
                f"expected {expected_version}{migration_hint}"
            )
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required = {"interpretation_entries", "interpretation_meta"}
        if not required.issubset(tables):
            raise StoreNotInitializedError(
                "interpretation schema marker exists but required tables are missing"
            )
        actual_columns = tuple(
            str(row[1])
            for row in connection.execute("PRAGMA table_info(interpretation_entries)")
        )
        if actual_columns != _ENTRY_COLUMNS:
            raise StoreNotInitializedError(
                "interpretation schema columns do not match this build; "
                "an explicit migration is required"
            )
        meta = connection.execute(
            "SELECT value FROM interpretation_meta WHERE key = 'schema_version'"
        ).fetchone()
        if meta is None or str(meta[0]) != str(expected_version):
            raise StoreNotInitializedError(
                "interpretation schema metadata disagrees with PRAGMA user_version"
            )

    @staticmethod
    def _migrate_v1_to_v2(connection: sqlite3.Connection) -> None:
        """Transactionally rebuild the entry table with self-aspect support."""

        migration_table = "interpretation_entries_v2_migration"
        columns = ", ".join(_ENTRY_COLUMNS)
        built_in_indexes = {
            "interpretation_entries_type_idx",
            "interpretation_entries_status_idx",
        }
        user_schema_objects = tuple(
            (str(row[0]), str(row[1]), str(row[2]))
            for row in connection.execute(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE tbl_name = 'interpretation_entries' "
                "AND type IN ('index', 'trigger') AND sql IS NOT NULL "
                "ORDER BY type, name"
            )
            if str(row[1]) not in built_in_indexes
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(_entry_table_sql(migration_table))
            connection.execute(
                f"INSERT INTO {migration_table} ({columns}) "
                f"SELECT {columns} FROM interpretation_entries"
            )
            connection.execute("DROP TABLE interpretation_entries")
            connection.execute(
                f"ALTER TABLE {migration_table} RENAME TO interpretation_entries"
            )
            for statement in _INDEX_SQL_STATEMENTS:
                connection.execute(statement)
            for _object_type, _object_name, statement in user_schema_objects:
                # Columns are unchanged between v1 and v2. Replaying a custom
                # object that is nevertheless incompatible fails the enclosing
                # transaction instead of silently discarding user schema work.
                connection.execute(statement)
            connection.execute(
                "UPDATE interpretation_meta SET value = ? "
                "WHERE key = 'schema_version'",
                (str(DATABASE_SCHEMA_VERSION),),
            )
            connection.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @staticmethod
    def _record_values(entry: InterpretationEntry) -> tuple[object, ...]:
        return (
            entry.id,
            entry.type,
            entry.planet,
            entry.sign,
            entry.house,
            entry.angle,
            entry.body_a,
            entry.body_b,
            entry.aspect_type,
            entry.pattern_type,
            entry.title,
            json.dumps(list(entry.keywords), ensure_ascii=False, separators=(",", ":")),
            entry.summary,
            entry.body,
            entry.shadow,
            entry.growth,
            entry.blend_note,
            entry.source,
            entry.license,
            entry.status,
            entry.version,
            entry.updated,
        )

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> InterpretationEntry:
        return InterpretationEntry(
            id=row["id"],
            type=row["entry_type"],
            planet=row["planet"],
            sign=row["sign"],
            house=row["house"],
            angle=row["angle"],
            body_a=row["body_a"],
            body_b=row["body_b"],
            aspect_type=row["aspect_type"],
            pattern_type=row["pattern_type"],
            title=row["title"],
            keywords=tuple(json.loads(row["keywords_json"])),
            summary=row["summary"],
            body=row["body"],
            shadow=row["shadow"],
            growth=row["growth"],
            blend_note=row["blend_note"],
            source=row["source"],
            license=row["license"],
            status=row["status"],
            version=row["version"],
            updated=row["updated"],
        )

    @staticmethod
    def _seed_files(path: str | Path) -> tuple[Path, ...]:
        source = Path(path)
        if source.is_file():
            return (source,)
        if source.is_dir():
            files = tuple(sorted(source.glob("*.json"), key=lambda item: item.name))
            if not files:
                raise SeedImportError(f"seed directory contains no JSON files: {source}")
            return files
        raise SeedImportError(f"seed path does not exist: {source}")

    @staticmethod
    def _load_seed_file(path: Path) -> tuple[InterpretationEntry, ...]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SeedImportError(f"cannot read seed file {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise SeedImportError(f"seed file must contain an object: {path}")
        if (
            type(payload.get("schema_version")) is not int
            or payload["schema_version"] != SEED_SCHEMA_VERSION
        ):
            raise SeedImportError(
                f"seed {path} has schema_version {payload.get('schema_version')!r}; "
                f"expected {SEED_SCHEMA_VERSION}"
            )
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise SeedImportError(f"seed records must be an array: {path}")
        entries: list[InterpretationEntry] = []
        try:
            for raw in raw_records:
                if not isinstance(raw, dict):
                    raise ValueError("each record must be an object")
                entries.append(InterpretationEntry.from_dict(raw))
        except (TypeError, ValueError) as exc:
            raise SeedImportError(f"invalid record in {path}: {exc}") from exc
        ids = [entry.id for entry in entries]
        if len(set(ids)) != len(ids):
            raise SeedImportError(f"duplicate record id within seed file: {path}")
        return tuple(entries)

    def import_path(self, path: str | Path) -> ImportResult:
        """Import one seed file or a sorted directory in one transaction.

        Higher record versions replace lower versions, lower versions are
        skipped, identical same-version records are no-ops, and divergent
        same-version records fail loudly. This makes Seed 0/1 order-independent.
        """

        connection = self._require_schema()
        files = self._seed_files(path)
        loaded = tuple((file, self._load_seed_file(file)) for file in files)
        inserted = updated = unchanged = skipped = 0
        placeholders = ", ".join("?" for _ in _ENTRY_COLUMNS)
        insert_sql = (
            f"INSERT INTO interpretation_entries ({', '.join(_ENTRY_COLUMNS)}) "
            f"VALUES ({placeholders})"
        )
        update_columns = _ENTRY_COLUMNS[1:]
        update_sql = (
            "UPDATE interpretation_entries SET "
            + ", ".join(f"{column} = ?" for column in update_columns)
            + " WHERE id = ?"
        )
        try:
            connection.execute("BEGIN")
            for file, entries in loaded:
                for entry in entries:
                    row = connection.execute(
                        "SELECT * FROM interpretation_entries WHERE id = ?", (entry.id,)
                    ).fetchone()
                    if row is None:
                        connection.execute(insert_sql, self._record_values(entry))
                        inserted += 1
                        continue
                    current = self._row_to_entry(row)
                    if entry.version < current.version:
                        skipped += 1
                    elif entry.version > current.version:
                        values = self._record_values(entry)
                        connection.execute(update_sql, values[1:] + (entry.id,))
                        updated += 1
                    elif entry.to_dict() == current.to_dict():
                        unchanged += 1
                    else:
                        raise SeedImportError(
                            f"same-version conflict for {entry.id!r} in {file}; "
                            "increment version rather than silently overwriting"
                        )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        records = sum(len(entries) for _, entries in loaded)
        return ImportResult(
            files=len(files),
            records=records,
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            skipped=skipped,
        )

    def get(self, entry_id: str) -> InterpretationEntry | None:
        connection = self._require_schema()
        row = connection.execute(
            "SELECT * FROM interpretation_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return None if row is None else self._row_to_entry(row)

    def get_many(self, entry_ids: Iterable[str]) -> dict[str, InterpretationEntry]:
        result: dict[str, InterpretationEntry] = {}
        for entry_id in dict.fromkeys(entry_ids):
            entry = self.get(entry_id)
            if entry is not None:
                result[entry_id] = entry
        return result

    def audit(self, expected_ids: Sequence[str] | None = None) -> InventoryAudit:
        expected = tuple(expected_entry_ids() if expected_ids is None else expected_ids)
        records = self.get_many(expected)
        ready_ids = tuple(key for key in expected if key in records and records[key].status != "stub")
        stub_ids = tuple(key for key in expected if key in records and records[key].status == "stub")
        missing_ids = tuple(key for key in expected if key not in records)
        return InventoryAudit(
            expected=len(expected),
            ready=len(ready_ids),
            stub=len(stub_ids),
            missing=len(missing_ids),
            ready_ids=ready_ids,
            stub_ids=stub_ids,
            missing_ids=missing_ids,
        )

    def iter_all(self) -> Iterator[InterpretationEntry]:
        connection = self._require_schema()
        rows = connection.execute("SELECT * FROM interpretation_entries ORDER BY id")
        for row in rows:
            yield self._row_to_entry(row)
