"""Local JSON library for saved two-natal synastry report snapshots.

Snapshots live under ``charts/synastry/`` by default (gitignored with charts).
They store the full composed report plus references to the natal chart ids so
the study can be reopened or re-interpreted later with a fresher DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping
import unicodedata

from .library import ChartLibraryError, ChartNotFoundError, AmbiguousChartError


SYNASTRY_SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_SYNASTRY_DIRNAME = "synastry"
_SLUG_LIMIT = 48
_SNAPSHOT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")
_SNAPSHOT_LABEL_LIMIT = 120
_CHART_LABEL_LIMIT = 240
_LINKED_ID_LIMIT = 240
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


def default_synastry_dir(charts_dir: Path | str = "charts") -> Path:
    return Path(charts_dir).expanduser() / DEFAULT_SYNASTRY_DIRNAME


@dataclass(frozen=True, slots=True)
class SavedSynastry:
    """One validated synastry snapshot on disk."""

    id: str
    label: str
    chart_a_id: str | None
    chart_b_id: str | None
    chart_a_label: str
    chart_b_label: str
    saved_at: str
    report: Mapping[str, Any]
    source_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SYNASTRY_SNAPSHOT_SCHEMA_VERSION,
            "type": "synastry_snapshot",
            "id": self.id,
            "label": self.label,
            "chart_a_id": self.chart_a_id,
            "chart_b_id": self.chart_b_id,
            "chart_a_label": self.chart_a_label,
            "chart_b_label": self.chart_b_label,
            "saved_at": self.saved_at,
            "report": dict(self.report),
        }

    def summary_dict(self) -> dict[str, Any]:
        rels = self.report.get("relationships")
        gap_n = len(self.report.get("gaps") or [])
        return {
            "id": self.id,
            "label": self.label,
            "chart_a_id": self.chart_a_id,
            "chart_b_id": self.chart_b_id,
            "chart_a_label": self.chart_a_label,
            "chart_b_label": self.chart_b_label,
            "saved_at": self.saved_at,
            "relationship_count": len(rels) if isinstance(rels, list) else 0,
            "gap_count": gap_n,
        }


def save_synastry_snapshot(
    report: Mapping[str, Any],
    *,
    label: str,
    charts_dir: Path | str = "charts",
    synastry_dir: Path | str | None = None,
    snapshot_id: str | None = None,
    chart_a_id: str | None = None,
    chart_b_id: str | None = None,
    overwrite: bool = False,
) -> SavedSynastry:
    """Persist a composed synastry report as a local snapshot."""

    if report.get("report_type") != "synastry":
        raise ChartLibraryError("Only synastry reports can be saved to the synastry library")
    if not isinstance(overwrite, bool):
        raise ChartLibraryError("overwrite must be a boolean")
    clean_label = _validate_label(label, "label", _SNAPSHOT_LABEL_LIMIT)

    chart_a = _mapping(report.get("chart_a"), "chart_a")
    chart_b = _mapping(report.get("chart_b"), "chart_b")
    label_a = _validate_label(
        chart_a.get("label") or "Chart A",
        "chart_a.label",
        _CHART_LABEL_LIMIT,
    )
    label_b = _validate_label(
        chart_b.get("label") or "Chart B",
        "chart_b.label",
        _CHART_LABEL_LIMIT,
    )
    id_a = _optional_str(
        chart_a_id if chart_a_id is not None else chart_a.get("id"),
        "chart_a_id",
    )
    id_b = _optional_str(
        chart_b_id if chart_b_id is not None else chart_b.get("id"),
        "chart_b_id",
    )

    directory = (
        Path(synastry_dir).expanduser()
        if synastry_dir is not None
        else default_synastry_dir(charts_dir)
    )
    _ensure_private_directory(directory)

    if snapshot_id is not None and not isinstance(snapshot_id, str):
        raise ChartLibraryError("Synastry snapshot id must be a string")
    supplied_id = (snapshot_id or "").strip()
    sid = supplied_id if supplied_id else _slugify(clean_label)
    if not sid:
        sid = f"synastry-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    sid = _validate_snapshot_id(sid)
    existing_ids = {path.stem.casefold(): path for path in directory.glob("*.json")}
    collision = existing_ids.get(sid.casefold())
    if collision is not None and collision.stem != sid:
        raise ChartLibraryError(
            f"Synastry snapshot id {sid!r} conflicts by letter case with {collision.stem!r}"
        )
    if collision is not None and not overwrite:
        if supplied_id:
            raise ChartLibraryError(
                f"Synastry snapshot id already exists: {sid}; use refresh to overwrite it"
            )
        sid = _next_available_id(sid, frozenset(existing_ids))
    path = directory / f"{sid}.json"
    if overwrite:
        if collision is None:
            raise ChartNotFoundError(f"No saved synastry matches {sid!r}")
        existing = _read_file(path)
        if (existing.chart_a_id, existing.chart_b_id) != (id_a, id_b):
            raise ChartLibraryError(
                "Refusing to overwrite a synastry snapshot linked to different natal charts"
            )
    payload = {
        "schema_version": SYNASTRY_SNAPSHOT_SCHEMA_VERSION,
        "type": "synastry_snapshot",
        "id": sid,
        "label": clean_label,
        "chart_a_id": id_a,
        "chart_b_id": id_b,
        "chart_a_label": label_a,
        "chart_b_label": label_b,
        "saved_at": datetime.now(UTC).isoformat(),
        "report": dict(report),
    }
    record = _record_from_payload(payload, path)
    _atomic_write_json(path, payload)
    return record


def list_synastries(
    charts_dir: Path | str = "charts",
    *,
    synastry_dir: Path | str | None = None,
) -> tuple[SavedSynastry, ...]:
    directory = (
        Path(synastry_dir).expanduser()
        if synastry_dir is not None
        else default_synastry_dir(charts_dir)
    )
    if not directory.exists():
        return ()
    if directory.is_symlink():
        raise ChartLibraryError(f"Refusing symlinked synastry directory: {directory}")
    if not directory.is_dir():
        raise ChartLibraryError(f"Synastry path is not a directory: {directory}")
    records = tuple(_read_file(path) for path in sorted(directory.glob("*.json")))
    return tuple(sorted(records, key=lambda item: (item.label.casefold(), item.id)))


def load_synastry(
    id_or_label: str,
    charts_dir: Path | str = "charts",
    *,
    synastry_dir: Path | str | None = None,
) -> SavedSynastry:
    identifier = id_or_label.strip()
    if not identifier:
        raise ChartNotFoundError("A non-empty synastry id or label is required")
    records = list_synastries(charts_dir, synastry_dir=synastry_dir)
    id_matches = tuple(item for item in records if item.id == identifier)
    if len(id_matches) == 1:
        return id_matches[0]
    label_matches = tuple(
        item for item in records if item.label.casefold() == identifier.casefold()
    )
    if len(label_matches) == 1:
        return label_matches[0]
    if len(label_matches) > 1:
        ids = ", ".join(item.id for item in label_matches)
        raise AmbiguousChartError(
            f"Label {identifier!r} matches multiple synastry snapshots: {ids}"
        )
    raise ChartNotFoundError(f"No saved synastry matches {identifier!r}")


def _record_from_payload(payload: Mapping[str, Any], path: Path) -> SavedSynastry:
    if payload.get("type") != "synastry_snapshot":
        raise ChartLibraryError(f"Not a synastry snapshot: {path}")
    version = payload.get("schema_version")
    if isinstance(version, bool) or version != SYNASTRY_SNAPSHOT_SCHEMA_VERSION:
        raise ChartLibraryError(
            f"Unsupported synastry snapshot schema_version in {path}: {version!r}"
        )
    report = payload.get("report")
    if not isinstance(report, Mapping):
        raise ChartLibraryError(f"Synastry snapshot missing report object: {path}")
    if report.get("report_type") != "synastry":
        raise ChartLibraryError(f"Synastry snapshot report_type must be 'synastry': {path}")
    for role, fallback in (("chart_a", "Chart A"), ("chart_b", "Chart B")):
        chart_summary = _mapping(report.get(role), f"report.{role}")
        _validate_label(
            chart_summary.get("label") or fallback,
            f"report.{role}.label",
            _CHART_LABEL_LIMIT,
        )
        _optional_str(chart_summary.get("id"), f"report.{role}.id")
    for field in ("relationships", "gaps", "warnings"):
        if not isinstance(report.get(field), list):
            raise ChartLibraryError(f"Synastry snapshot report.{field} must be an array: {path}")
    if any(not isinstance(item, Mapping) for item in report["relationships"]):
        raise ChartLibraryError(
            f"Synastry snapshot report.relationships entries must be objects: {path}"
        )
    if any(not isinstance(item, Mapping) for item in report["gaps"]):
        raise ChartLibraryError(
            f"Synastry snapshot report.gaps entries must be objects: {path}"
        )
    if any(not isinstance(item, str) for item in report["warnings"]):
        raise ChartLibraryError(
            f"Synastry snapshot report.warnings entries must be strings: {path}"
        )
    raw_id = payload.get("id")
    if not isinstance(raw_id, str):
        raise ChartLibraryError(f"Synastry snapshot id must be a string: {path}")
    sid = _validate_snapshot_id(raw_id.strip())
    if sid != path.stem:
        raise ChartLibraryError(
            f"Synastry snapshot id {sid!r} does not match filename {path.name!r}"
        )
    label = _validate_label(payload.get("label"), "label", _SNAPSHOT_LABEL_LIMIT)
    chart_a_label = _validate_label(
        payload.get("chart_a_label"),
        "chart_a_label",
        _CHART_LABEL_LIMIT,
    )
    chart_b_label = _validate_label(
        payload.get("chart_b_label"),
        "chart_b_label",
        _CHART_LABEL_LIMIT,
    )
    saved_at = payload.get("saved_at")
    if not isinstance(saved_at, str) or _has_control_characters(saved_at):
        raise ChartLibraryError(f"Synastry snapshot saved_at must be a string: {path}")
    if len(saved_at) > 80:
        raise ChartLibraryError(f"Synastry snapshot saved_at is too long: {path}")
    return SavedSynastry(
        id=sid,
        label=label,
        chart_a_id=_optional_str(payload.get("chart_a_id"), "chart_a_id"),
        chart_b_id=_optional_str(payload.get("chart_b_id"), "chart_b_id"),
        chart_a_label=chart_a_label,
        chart_b_label=chart_b_label,
        saved_at=saved_at,
        report=dict(report),
        source_path=path,
    )


def _read_file(path: Path) -> SavedSynastry:
    if path.is_symlink():
        raise ChartLibraryError(f"Refusing symlinked synastry snapshot: {path}")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ChartLibraryError(f"Could not read synastry snapshot {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ChartLibraryError(f"Synastry snapshot must be a JSON object: {path}")
    return _record_from_payload(payload, path)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChartLibraryError(f"{name} must be an object")
    return value


def _optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ChartLibraryError(f"{name} must be a string or null")
    text = value.strip()
    if len(text) > _LINKED_ID_LIMIT or _has_control_characters(text):
        raise ChartLibraryError(f"{name} is not a valid linked chart id")
    return text or None


def _slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug[:_SLUG_LIMIT].strip("-")


def _next_available_id(base: str, existing_casefold_ids: frozenset[str]) -> str:
    for suffix in range(2, 10_000):
        token = f"-{suffix}"
        candidate = f"{base[: 96 - len(token)].rstrip('-')}{token}"
        if candidate.casefold() not in existing_casefold_ids:
            return candidate
    raise ChartLibraryError("Could not allocate a unique synastry snapshot id")


def _validate_snapshot_id(value: str) -> str:
    if not _SNAPSHOT_ID.fullmatch(value) or value.casefold() in _WINDOWS_RESERVED_NAMES:
        raise ChartLibraryError(
            "Synastry snapshot id must use 1–96 lowercase ASCII letters, numbers, "
            "underscores, or hyphens and must not be a reserved filename"
        )
    return value


def _validate_label(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ChartLibraryError(f"{name} must be a string")
    text = value.strip()
    if not text:
        raise ChartLibraryError(f"{name} must not be empty")
    if len(text) > limit:
        raise ChartLibraryError(f"{name} must be at most {limit} characters")
    if _has_control_characters(text):
        raise ChartLibraryError(f"{name} must not contain control characters")
    return text


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _ensure_private_directory(directory: Path) -> None:
    if directory.is_symlink():
        raise ChartLibraryError(f"Refusing symlinked synastry directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


__all__ = [
    "DEFAULT_SYNASTRY_DIRNAME",
    "SYNASTRY_SNAPSHOT_SCHEMA_VERSION",
    "SavedSynastry",
    "default_synastry_dir",
    "list_synastries",
    "load_synastry",
    "save_synastry_snapshot",
]
