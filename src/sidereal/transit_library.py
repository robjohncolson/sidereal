"""Local JSON library for saved transit-study snapshots.

Snapshots live under ``charts/transits/`` by default. Each file holds the full
composed transit report plus natal/transit moment references so a human or
agent can reopen the study for conversation, or refresh it from linked natals
and the current interpretation DB.

A companion ``.md`` file is written beside the JSON for easy agent context.
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

from .library import AmbiguousChartError, ChartLibraryError, ChartNotFoundError


TRANSIT_SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_TRANSIT_DIRNAME = "transits"
_SLUG_LIMIT = 48
_SNAPSHOT_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}\Z")
_SNAPSHOT_LABEL_LIMIT = 120
_LABEL_LIMIT = 240
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


def default_transit_dir(charts_dir: Path | str = "charts") -> Path:
    return Path(charts_dir).expanduser() / DEFAULT_TRANSIT_DIRNAME


@dataclass(frozen=True, slots=True)
class SavedTransit:
    """One validated transit snapshot on disk."""

    id: str
    label: str
    natal_id: str | None
    natal_label: str
    transit_label: str
    transit_local_datetime: str
    saved_at: str
    report: Mapping[str, Any]
    markdown: str
    source_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TRANSIT_SNAPSHOT_SCHEMA_VERSION,
            "type": "transit_snapshot",
            "id": self.id,
            "label": self.label,
            "natal_id": self.natal_id,
            "natal_label": self.natal_label,
            "transit_label": self.transit_label,
            "transit_local_datetime": self.transit_local_datetime,
            "saved_at": self.saved_at,
            "report": dict(self.report),
            "markdown": self.markdown,
        }

    def summary_dict(self) -> dict[str, Any]:
        rels = self.report.get("relationships")
        placements = self.report.get("placements")
        return {
            "id": self.id,
            "label": self.label,
            "natal_id": self.natal_id,
            "natal_label": self.natal_label,
            "transit_label": self.transit_label,
            "transit_local_datetime": self.transit_local_datetime,
            "saved_at": self.saved_at,
            "relationship_count": len(rels) if isinstance(rels, list) else 0,
            "placement_count": len(placements) if isinstance(placements, list) else 0,
            "gap_count": len(self.report.get("gaps") or []),
            "markdown_path": str(self.source_path.with_suffix(".md")),
            "json_path": str(self.source_path),
        }


def save_transit_snapshot(
    report: Mapping[str, Any],
    *,
    label: str,
    markdown: str = "",
    charts_dir: Path | str = "charts",
    transit_dir: Path | str | None = None,
    snapshot_id: str | None = None,
    natal_id: str | None = None,
    overwrite: bool = False,
) -> SavedTransit:
    """Persist a composed transit report as a local snapshot (+ companion .md)."""

    if report.get("report_type") != "transit":
        raise ChartLibraryError("Only transit reports can be saved to the transit library")
    if not isinstance(overwrite, bool):
        raise ChartLibraryError("overwrite must be a boolean")
    clean_label = _validate_label(label, "label", _SNAPSHOT_LABEL_LIMIT)

    natal = _mapping(report.get("natal"), "natal")
    transit = _mapping(report.get("transit"), "transit")
    natal_label = _validate_label(
        natal.get("label") or "Natal",
        "natal.label",
        _LABEL_LIMIT,
    )
    transit_label = _validate_label(
        transit.get("label") or "Transit",
        "transit.label",
        _LABEL_LIMIT,
    )
    transit_dt = str(transit.get("local_datetime") or "").strip()
    if not transit_dt or _has_control_characters(transit_dt) or len(transit_dt) > 80:
        raise ChartLibraryError("Transit report is missing a valid transit.local_datetime")
    linked_natal = _optional_str(
        natal_id if natal_id is not None else natal.get("id"),
        "natal_id",
    )

    directory = (
        Path(transit_dir).expanduser()
        if transit_dir is not None
        else default_transit_dir(charts_dir)
    )
    _ensure_private_directory(directory)

    if snapshot_id is not None and not isinstance(snapshot_id, str):
        raise ChartLibraryError("Transit snapshot id must be a string")
    supplied_id = (snapshot_id or "").strip()
    sid = supplied_id if supplied_id else _slugify(clean_label)
    if not sid:
        sid = f"transit-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    sid = _validate_snapshot_id(sid)
    existing_ids = {path.stem.casefold(): path for path in directory.glob("*.json")}
    collision = existing_ids.get(sid.casefold())
    if collision is not None and collision.stem != sid:
        raise ChartLibraryError(
            f"Transit snapshot id {sid!r} conflicts by letter case with {collision.stem!r}"
        )
    if collision is not None and not overwrite:
        if supplied_id:
            raise ChartLibraryError(
                f"Transit snapshot id already exists: {sid}; use refresh to overwrite it"
            )
        sid = _next_available_id(sid, frozenset(existing_ids))
    path = directory / f"{sid}.json"
    if overwrite:
        if collision is None:
            raise ChartNotFoundError(f"No saved transit matches {sid!r}")
        existing = _read_file(path)
        if existing.natal_id and linked_natal and existing.natal_id != linked_natal:
            raise ChartLibraryError(
                "Refusing to overwrite a transit snapshot linked to a different natal chart"
            )

    md_text = markdown if isinstance(markdown, str) else ""
    if not md_text.strip():
        md_text = _fallback_markdown(report, clean_label)

    payload = {
        "schema_version": TRANSIT_SNAPSHOT_SCHEMA_VERSION,
        "type": "transit_snapshot",
        "id": sid,
        "label": clean_label,
        "natal_id": linked_natal,
        "natal_label": natal_label,
        "transit_label": transit_label,
        "transit_local_datetime": transit_dt,
        "saved_at": datetime.now(UTC).isoformat(),
        "report": dict(report),
        "markdown": md_text,
    }
    record = _record_from_payload(payload, path)
    _atomic_write_json(path, payload)
    _atomic_write_text(path.with_suffix(".md"), md_text)
    return record


def list_transits(
    charts_dir: Path | str = "charts",
    *,
    transit_dir: Path | str | None = None,
) -> tuple[SavedTransit, ...]:
    directory = (
        Path(transit_dir).expanduser()
        if transit_dir is not None
        else default_transit_dir(charts_dir)
    )
    if not directory.exists():
        return ()
    if directory.is_symlink():
        raise ChartLibraryError(f"Refusing symlinked transit directory: {directory}")
    if not directory.is_dir():
        raise ChartLibraryError(f"Transit path is not a directory: {directory}")
    records = tuple(_read_file(path) for path in sorted(directory.glob("*.json")))
    return tuple(sorted(records, key=lambda item: (item.label.casefold(), item.id)))


def load_transit(
    id_or_label: str,
    charts_dir: Path | str = "charts",
    *,
    transit_dir: Path | str | None = None,
) -> SavedTransit:
    identifier = id_or_label.strip()
    if not identifier:
        raise ChartNotFoundError("A non-empty transit id or label is required")
    records = list_transits(charts_dir, transit_dir=transit_dir)
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
            f"Label {identifier!r} matches multiple transit snapshots: {ids}"
        )
    raise ChartNotFoundError(f"No saved transit matches {identifier!r}")


def _record_from_payload(payload: Mapping[str, Any], path: Path) -> SavedTransit:
    if payload.get("type") != "transit_snapshot":
        raise ChartLibraryError(f"Not a transit snapshot: {path}")
    version = payload.get("schema_version")
    if isinstance(version, bool) or version != TRANSIT_SNAPSHOT_SCHEMA_VERSION:
        raise ChartLibraryError(
            f"Unsupported transit snapshot schema_version in {path}: {version!r}"
        )
    report = payload.get("report")
    if not isinstance(report, Mapping):
        raise ChartLibraryError(f"Transit snapshot missing report object: {path}")
    if report.get("report_type") != "transit":
        raise ChartLibraryError(f"Transit snapshot report_type must be 'transit': {path}")
    for role in ("natal", "transit"):
        _mapping(report.get(role), f"report.{role}")
    for field in ("placements", "relationships", "gaps", "warnings"):
        if not isinstance(report.get(field), list):
            raise ChartLibraryError(
                f"Transit snapshot report.{field} must be an array: {path}"
            )
    raw_id = payload.get("id")
    if not isinstance(raw_id, str):
        raise ChartLibraryError(f"Transit snapshot id must be a string: {path}")
    sid = _validate_snapshot_id(raw_id.strip())
    if sid != path.stem:
        raise ChartLibraryError(
            f"Transit snapshot id {sid!r} does not match filename {path.name!r}"
        )
    label = _validate_label(payload.get("label"), "label", _SNAPSHOT_LABEL_LIMIT)
    natal_label = _validate_label(payload.get("natal_label"), "natal_label", _LABEL_LIMIT)
    transit_label = _validate_label(
        payload.get("transit_label"), "transit_label", _LABEL_LIMIT
    )
    saved_at = payload.get("saved_at")
    if not isinstance(saved_at, str) or _has_control_characters(saved_at):
        raise ChartLibraryError(f"Transit snapshot saved_at must be a string: {path}")
    transit_dt = payload.get("transit_local_datetime")
    if not isinstance(transit_dt, str) or _has_control_characters(transit_dt):
        raise ChartLibraryError(
            f"Transit snapshot transit_local_datetime must be a string: {path}"
        )
    markdown = payload.get("markdown", "")
    if not isinstance(markdown, str):
        raise ChartLibraryError(f"Transit snapshot markdown must be a string: {path}")
    return SavedTransit(
        id=sid,
        label=label,
        natal_id=_optional_str(payload.get("natal_id"), "natal_id"),
        natal_label=natal_label,
        transit_label=transit_label,
        transit_local_datetime=transit_dt,
        saved_at=saved_at,
        report=dict(report),
        markdown=markdown,
        source_path=path,
    )


def _read_file(path: Path) -> SavedTransit:
    if path.is_symlink():
        raise ChartLibraryError(f"Refusing symlinked transit snapshot: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChartLibraryError(f"Could not read transit snapshot {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ChartLibraryError(f"Transit snapshot must be a JSON object: {path}")
    return _record_from_payload(payload, path)


def _fallback_markdown(report: Mapping[str, Any], label: str) -> str:
    natal = report.get("natal") if isinstance(report.get("natal"), Mapping) else {}
    transit = report.get("transit") if isinstance(report.get("transit"), Mapping) else {}
    lines = [
        f"# Transit study: {label}",
        "",
        f"Natal: {natal.get('label', 'unknown')} · {natal.get('local_datetime', 'unknown')}",
        f"Transit: {transit.get('label', 'unknown')} · {transit.get('local_datetime', 'unknown')}",
        "",
        str(report.get("epistemic_note") or ""),
        "",
        f"Placements: {len(report.get('placements') or [])}",
        f"Relationships: {len(report.get('relationships') or [])}",
        f"Gaps: {len(report.get('gaps') or [])}",
        "",
        "Open the companion JSON for full geometry and interpretation records.",
        "",
    ]
    return "\n".join(lines)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChartLibraryError(f"{name} must be an object")
    return value


def _optional_str(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ChartLibraryError(f"{name} must be a string when provided")
    text = value.strip()
    if _has_control_characters(text):
        raise ChartLibraryError(f"{name} contains control characters")
    if len(text) > 240:
        raise ChartLibraryError(f"{name} is too long")
    return text or None


def _validate_label(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ChartLibraryError(f"{name} must be a string")
    text = value.strip()
    if not text:
        raise ChartLibraryError(f"{name} must be non-empty")
    if _has_control_characters(text):
        raise ChartLibraryError(f"{name} contains control characters")
    if len(text) > limit:
        raise ChartLibraryError(f"{name} is too long (max {limit})")
    return text


def _validate_snapshot_id(value: str) -> str:
    text = value.strip()
    if not _SNAPSHOT_ID.fullmatch(text):
        raise ChartLibraryError(
            "Transit snapshot id must be lowercase letters, digits, underscore, or hyphen"
        )
    if text.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES:
        raise ChartLibraryError(f"Transit snapshot id uses a reserved name: {text}")
    return text


def _slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug[:_SLUG_LIMIT].strip("-")


def _next_available_id(base: str, existing: frozenset[str]) -> str:
    if base.casefold() not in existing:
        return base
    for index in range(2, 1000):
        candidate = f"{base}-{index}"
        if candidate.casefold() not in existing:
            return candidate
    raise ChartLibraryError(f"Could not allocate a unique transit snapshot id from {base!r}")


def _has_control_characters(value: str) -> bool:
    return any(ord(char) < 32 for char in value)


def _ensure_private_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
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
    "DEFAULT_TRANSIT_DIRNAME",
    "TRANSIT_SNAPSHOT_SCHEMA_VERSION",
    "SavedTransit",
    "default_transit_dir",
    "list_transits",
    "load_transit",
    "save_transit_snapshot",
]
