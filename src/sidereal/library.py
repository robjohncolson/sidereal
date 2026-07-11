"""Small, local JSON library for saved chart geometry.

Saved files contain birth data and should be treated as sensitive.  The
library writes them beneath ``charts/`` by default, with owner-only file and
directory permissions where the platform supports POSIX modes.  It stores no
database credentials, API tokens, or other application secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Mapping
import unicodedata

from .config import AspectRule, ChartConfig
from .types import (
    AspectHit,
    Chart,
    ChartMeta,
    HouseCusp,
    MomentInput,
    PatternHit,
    PointPos,
)


SAVED_CHART_SCHEMA_VERSION = 1
DEFAULT_CHARTS_DIR = Path("charts")
_SLUG_LIMIT = 48


class ChartLibraryError(ValueError):
    """Base exception for an invalid or ambiguous saved-chart record."""


class ChartNotFoundError(FileNotFoundError):
    """Raised when no saved chart matches an id or label."""


class AmbiguousChartError(ChartLibraryError):
    """Raised when a label identifies more than one saved chart."""


@dataclass(frozen=True, slots=True)
class SavedChart:
    """Validated saved-chart payload plus its local source path."""

    id: str
    label: str
    local_datetime: str
    tz: str
    systems: tuple[str, ...]
    input: dict[str, Any]
    config: dict[str, Any]
    chart: dict[str, Any]
    last_report_path: str | None
    source_path: Path

    @property
    def path(self) -> Path:
        """Compatibility-friendly alias for the local JSON source path."""

        return self.source_path

    def moment(self) -> MomentInput:
        """Reconstruct the civil input used for the saved geometry."""

        return moment_from_dict(self.input)

    def chart_config(self) -> ChartConfig:
        """Reconstruct and validate the calculation configuration."""

        return config_from_dict(self.config)

    def chart_object(self) -> Chart:
        """Reconstruct the frozen geometry snapshot stored in this record."""

        return chart_from_dict(self.chart)

    def to_dict(self) -> dict[str, Any]:
        """Return the persistent payload without the machine-local source path."""

        return {
            "schema_version": SAVED_CHART_SCHEMA_VERSION,
            "id": self.id,
            "label": self.label,
            "local_datetime": self.local_datetime,
            "tz": self.tz,
            "systems": list(self.systems),
            "input": _json_copy(self.input),
            "config": _json_copy(self.config),
            "chart": _json_copy(self.chart),
            "last_report_path": self.last_report_path,
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the record deterministically as strict JSON."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
            allow_nan=False,
        )


def save_chart(
    chart: Chart,
    config: ChartConfig,
    *,
    charts_dir: Path | str = DEFAULT_CHARTS_DIR,
    systems: Iterable[str] | None = None,
    last_report_path: Path | str | None = None,
) -> SavedChart:
    """Atomically save ``chart`` and return its validated library record.

    The stable id combines a label slug, the chart's UTC instant, and a short
    fingerprint of its input/config. Saving the same chart again updates that
    record, while same-time charts with different inputs remain distinct.
    """

    config.validate()
    if chart.meta.zodiac_system != config.zodiac:
        raise ChartLibraryError(
            "Chart zodiac metadata does not match the configuration being saved"
        )
    directory = Path(charts_dir).expanduser()
    _ensure_private_directory(directory)

    label = chart.meta.input.label
    selected_systems = _normalize_systems(systems, chart.meta.zodiac_system)
    input_payload = moment_to_dict(chart.meta.input)
    config_payload = config_to_dict(config)
    chart_id = (
        f"{_slugify(label)}-{_utc_token(chart.meta.utc_datetime)}-"
        f"{_record_fingerprint(input_payload, config_payload)}"
    )
    path = directory / f"{chart_id}.json"
    chart_payload = chart.to_dict()
    nested_input = chart_payload.get("meta", {}).get("input")
    if nested_input != input_payload:  # pragma: no cover - internal consistency guard
        raise ChartLibraryError("Chart metadata input did not serialize consistently")

    payload = {
        "schema_version": SAVED_CHART_SCHEMA_VERSION,
        "id": chart_id,
        "label": label,
        "local_datetime": chart.meta.local_datetime.isoformat(),
        "tz": chart.meta.input.tz,
        "systems": list(selected_systems),
        "input": input_payload,
        "config": config_payload,
        "chart": chart_payload,
        "last_report_path": (
            _path_string(str(last_report_path), "last_report_path")
            if last_report_path is not None
            else None
        ),
    }
    record = _record_from_payload(payload, path)
    _atomic_write_json(path, payload)
    return record


def list_charts(
    charts_dir: Path | str = DEFAULT_CHARTS_DIR,
) -> tuple[SavedChart, ...]:
    """Return validated saved charts in stable label/id order."""

    directory = Path(charts_dir).expanduser()
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise ChartLibraryError(f"Charts path is not a directory: {directory}")
    records = tuple(_read_chart_file(path) for path in sorted(directory.glob("*.json")))
    return tuple(sorted(records, key=lambda item: (item.label.casefold(), item.id)))


def load_chart(
    id_or_label: str,
    charts_dir: Path | str = DEFAULT_CHARTS_DIR,
) -> SavedChart:
    """Resolve one saved chart, preferring an exact id over a label."""

    identifier = id_or_label.strip()
    if not identifier:
        raise ChartNotFoundError("A non-empty saved chart id or label is required")
    records = list_charts(charts_dir)

    id_matches = tuple(
        item
        for item in records
        if item.id == identifier or item.source_path.name == identifier
    )
    if id_matches:
        return id_matches[0]

    exact_labels = tuple(item for item in records if item.label == identifier)
    if exact_labels:
        return _require_one_label(identifier, exact_labels)

    folded_labels = tuple(
        item for item in records if item.label.casefold() == identifier.casefold()
    )
    if folded_labels:
        return _require_one_label(identifier, folded_labels)
    raise ChartNotFoundError(f"No saved chart matches {id_or_label!r}")


def update_last_report_path(
    id_or_label: str,
    report_path: Path | str | None,
    *,
    charts_dir: Path | str = DEFAULT_CHARTS_DIR,
) -> SavedChart:
    """Update the optional last-report pointer without changing geometry."""

    record = load_chart(id_or_label, charts_dir)
    payload = record.to_dict()
    payload["last_report_path"] = (
        _path_string(str(report_path), "last_report_path")
        if report_path is not None
        else None
    )
    updated = _record_from_payload(payload, record.source_path)
    _atomic_write_json(record.source_path, payload)
    return updated


def moment_to_dict(moment: MomentInput) -> dict[str, Any]:
    """Encode a :class:`MomentInput` using only stable JSON primitives."""

    return {
        "local_date": moment.local_date.isoformat(),
        "local_time": moment.local_time.isoformat() if moment.local_time is not None else None,
        "tz": moment.tz,
        "lat": moment.lat,
        "lon": moment.lon,
        "label": moment.label,
        "fold": moment.fold,
    }


def moment_from_dict(payload: Mapping[str, Any]) -> MomentInput:
    """Decode and validate the stable saved-chart civil input."""

    if not isinstance(payload, Mapping):
        raise ChartLibraryError("Saved chart input must be an object")
    try:
        local_date = date.fromisoformat(_required_string(payload, "local_date"))
        raw_time = payload.get("local_time")
        local_time = None if raw_time is None else time.fromisoformat(_string(raw_time, "local_time"))
    except ValueError as exc:
        raise ChartLibraryError(f"Invalid saved civil date/time: {exc}") from exc
    if local_time is not None and local_time.tzinfo is not None:
        raise ChartLibraryError("Saved local_time must be a naive civil time")

    tz = _required_string(payload, "tz")
    lat = _optional_finite_float(payload.get("lat"), "lat")
    lon = _optional_finite_float(payload.get("lon"), "lon")
    if (lat is None) != (lon is None):
        raise ChartLibraryError("Saved lat and lon must be supplied together")
    if lat is not None and not -90.0 < lat < 90.0:
        raise ChartLibraryError("Saved lat must be strictly between -90 and 90 degrees")
    if lon is not None and not -180.0 <= lon <= 180.0:
        raise ChartLibraryError("Saved lon must be between -180 and 180 degrees")

    label = _string(payload.get("label", ""), "label")
    fold = payload.get("fold")
    if isinstance(fold, bool) or fold not in (None, 0, 1):
        raise ChartLibraryError("Saved fold must be 0, 1, or null")
    if fold is not None and local_time is None:
        raise ChartLibraryError("Saved fold requires a local_time")
    return MomentInput(local_date, local_time, tz, lat, lon, label, fold)


def config_to_dict(config: ChartConfig) -> dict[str, Any]:
    """Encode every calculation choice needed to reproduce a chart."""

    config.validate()
    return {
        "zodiac": config.zodiac,
        "house_system": config.house_system,
        "blend_orb_deg": config.blend_orb_deg,
        "aspect_profile": config.aspect_profile,
        "aspect_rules": [
            {"id": rule.id, "angle_deg": rule.angle_deg, "orb_deg": rule.orb_deg}
            for rule in config.aspect_rules
        ],
        "luminary_orb_bonus_deg": config.luminary_orb_bonus_deg,
        "outer_pair_orb_penalty_deg": config.outer_pair_orb_penalty_deg,
        "assumed_local_time": config.assumed_local_time.isoformat(),
        "boundary_path": str(config.boundary_path) if config.boundary_path is not None else None,
        "ephe_path": str(config.ephe_path) if config.ephe_path is not None else None,
        "require_swiss_ephemeris": config.require_swiss_ephemeris,
        "include_houses": config.include_houses,
        "include_patterns": config.include_patterns,
    }


def config_from_dict(payload: Mapping[str, Any]) -> ChartConfig:
    """Decode and validate a complete saved calculation configuration."""

    if not isinstance(payload, Mapping):
        raise ChartLibraryError("Saved chart config must be an object")
    rules_payload = payload.get("aspect_rules")
    if not isinstance(rules_payload, list):
        raise ChartLibraryError("Saved aspect_rules must be a list")
    rules: list[AspectRule] = []
    for index, item in enumerate(rules_payload):
        if not isinstance(item, Mapping):
            raise ChartLibraryError(f"Saved aspect_rules[{index}] must be an object")
        rules.append(
            AspectRule(
                id=_required_string(item, "id"),
                angle_deg=_finite_float(item.get("angle_deg"), f"aspect_rules[{index}].angle_deg"),
                orb_deg=_finite_float(item.get("orb_deg"), f"aspect_rules[{index}].orb_deg"),
            )
        )
    try:
        assumed_time = time.fromisoformat(_required_string(payload, "assumed_local_time"))
    except ValueError as exc:
        raise ChartLibraryError(f"Invalid saved assumed_local_time: {exc}") from exc
    if assumed_time.tzinfo is not None:
        raise ChartLibraryError("Saved assumed_local_time must be naive")

    config = ChartConfig(
        zodiac=_required_string(payload, "zodiac"),
        house_system=_required_string(payload, "house_system"),
        blend_orb_deg=_finite_float(payload.get("blend_orb_deg"), "blend_orb_deg"),
        aspect_profile=_required_string(payload, "aspect_profile"),
        aspect_rules=tuple(rules),
        luminary_orb_bonus_deg=_finite_float(
            payload.get("luminary_orb_bonus_deg"), "luminary_orb_bonus_deg"
        ),
        outer_pair_orb_penalty_deg=_finite_float(
            payload.get("outer_pair_orb_penalty_deg"), "outer_pair_orb_penalty_deg"
        ),
        assumed_local_time=assumed_time,
        boundary_path=_optional_path(payload.get("boundary_path"), "boundary_path"),
        ephe_path=_optional_path(payload.get("ephe_path"), "ephe_path"),
        require_swiss_ephemeris=_boolean(
            payload.get("require_swiss_ephemeris"), "require_swiss_ephemeris"
        ),
        include_houses=_boolean(payload.get("include_houses"), "include_houses"),
        include_patterns=_boolean(payload.get("include_patterns"), "include_patterns"),
    )
    try:
        config.validate()
    except ValueError as exc:
        raise ChartLibraryError(f"Invalid saved chart config: {exc}") from exc
    return config


def chart_from_dict(payload: Mapping[str, Any]) -> Chart:
    """Reconstruct every frozen chart dataclass from stored geometry JSON."""

    if not isinstance(payload, Mapping):
        raise ChartLibraryError("Saved chart geometry must be an object")
    meta_payload = _required_mapping(payload, "meta")
    input_payload = _required_mapping(meta_payload, "input")
    meta = ChartMeta(
        input=moment_from_dict(input_payload),
        time_known=_boolean(meta_payload.get("time_known"), "meta.time_known"),
        location_known=_boolean(
            meta_payload.get("location_known"), "meta.location_known"
        ),
        local_datetime=_aware_datetime(meta_payload.get("local_datetime"), "meta.local_datetime"),
        utc_datetime=_aware_datetime(meta_payload.get("utc_datetime"), "meta.utc_datetime"),
        jd_ut=_finite_float(meta_payload.get("jd_ut"), "meta.jd_ut"),
        jd_et=_finite_float(meta_payload.get("jd_et"), "meta.jd_et"),
        zodiac_system=_required_string(meta_payload, "zodiac_system"),
        house_system=_optional_string(meta_payload.get("house_system"), "meta.house_system"),
        aspect_profile=_required_string(meta_payload, "aspect_profile"),
        swe_version=_string(meta_payload.get("swe_version"), "meta.swe_version"),
        pyswisseph_version=_string(
            meta_payload.get("pyswisseph_version"), "meta.pyswisseph_version"
        ),
        boundary_version=_string(
            meta_payload.get("boundary_version"), "meta.boundary_version"
        ),
        ephemeris_backend=_required_string(meta_payload, "ephemeris_backend"),
        calculation_time_assumption=_optional_string(
            meta_payload.get("calculation_time_assumption"),
            "meta.calculation_time_assumption",
        ),
        warnings=_string_tuple(meta_payload.get("warnings"), "meta.warnings"),
        blend_orb_deg=_finite_float(
            meta_payload.get("blend_orb_deg"), "meta.blend_orb_deg"
        ),
        aspect_rules=_meta_aspect_rules(meta_payload.get("aspect_rules")),
        luminary_orb_bonus_deg=_finite_float(
            meta_payload.get("luminary_orb_bonus_deg"),
            "meta.luminary_orb_bonus_deg",
        ),
        outer_pair_orb_penalty_deg=_finite_float(
            meta_payload.get("outer_pair_orb_penalty_deg"),
            "meta.outer_pair_orb_penalty_deg",
        ),
        houses_enabled=_boolean(
            meta_payload.get("houses_enabled"), "meta.houses_enabled"
        ),
        patterns_enabled=_boolean(
            meta_payload.get("patterns_enabled"), "meta.patterns_enabled"
        ),
        ephemeris_flags=_string_tuple(
            meta_payload.get("ephemeris_flags"), "meta.ephemeris_flags"
        ),
        house_frame_method=_optional_string(
            meta_payload.get("house_frame_method"), "meta.house_frame_method"
        ),
        boundary_source_doi=_string(
            meta_payload.get("boundary_source_doi"), "meta.boundary_source_doi"
        ),
        boundary_license_id=_string(
            meta_payload.get("boundary_license_id"), "meta.boundary_license_id"
        ),
        boundary_sha256=_string(
            meta_payload.get("boundary_sha256"), "meta.boundary_sha256"
        ),
    )

    points = tuple(
        _point_from_dict(item, index)
        for index, item in enumerate(_required_list(payload, "points"))
    )
    raw_cusps = payload.get("cusps")
    cusps = (
        None
        if raw_cusps is None
        else tuple(
            _cusp_from_dict(item, index)
            for index, item in enumerate(_list(raw_cusps, "cusps"))
        )
    )
    aspects = tuple(
        _aspect_from_dict(item, index)
        for index, item in enumerate(_required_list(payload, "aspects"))
    )
    patterns = tuple(
        _pattern_from_dict(item, index)
        for index, item in enumerate(_required_list(payload, "patterns"))
    )
    return Chart(meta=meta, points=points, cusps=cusps, aspects=aspects, patterns=patterns)


def _point_from_dict(value: Any, index: int) -> PointPos:
    name = f"points[{index}]"
    item = _mapping(value, name)
    return PointPos(
        id=_required_string(item, "id"),
        name=_required_string(item, "name"),
        kind=_required_string(item, "kind"),
        lon_date=_finite_float(item.get("lon_date"), f"{name}.lon_date"),
        lon_j2000=_finite_float(item.get("lon_j2000"), f"{name}.lon_j2000"),
        lat=_finite_float(item.get("lat"), f"{name}.lat"),
        speed_long=_finite_float(item.get("speed_long"), f"{name}.speed_long"),
        retro=_boolean(item.get("retro"), f"{name}.retro"),
        sign=_required_string(item, "sign"),
        degree_in_sign=_finite_float(
            item.get("degree_in_sign"), f"{name}.degree_in_sign"
        ),
        house=_optional_integer(item.get("house"), f"{name}.house", minimum=1, maximum=12),
        blend=_boolean(item.get("blend"), f"{name}.blend"),
        secondary_sign=_optional_string(
            item.get("secondary_sign"), f"{name}.secondary_sign"
        ),
    )


def _cusp_from_dict(value: Any, index: int) -> HouseCusp:
    name = f"cusps[{index}]"
    item = _mapping(value, name)
    return HouseCusp(
        number=_integer(item.get("number"), f"{name}.number", minimum=1, maximum=12),
        lon_date=_finite_float(item.get("lon_date"), f"{name}.lon_date"),
        lon_j2000=_finite_float(item.get("lon_j2000"), f"{name}.lon_j2000"),
        sign=_required_string(item, "sign"),
        degree_in_sign=_finite_float(
            item.get("degree_in_sign"), f"{name}.degree_in_sign"
        ),
        blend=_boolean(item.get("blend"), f"{name}.blend"),
        secondary_sign=_optional_string(
            item.get("secondary_sign"), f"{name}.secondary_sign"
        ),
    )


def _aspect_from_dict(value: Any, index: int) -> AspectHit:
    name = f"aspects[{index}]"
    item = _mapping(value, name)
    applying = item.get("applying")
    if applying is not None and not isinstance(applying, bool):
        raise ChartLibraryError(f"Saved {name}.applying must be a boolean or null")
    return AspectHit(
        body_a=_required_string(item, "body_a"),
        body_b=_required_string(item, "body_b"),
        aspect_id=_required_string(item, "aspect_id"),
        separation=_finite_float(item.get("separation"), f"{name}.separation"),
        orb_used=_finite_float(item.get("orb_used"), f"{name}.orb_used"),
        exactness=_finite_float(item.get("exactness"), f"{name}.exactness"),
        force=_finite_float(item.get("force"), f"{name}.force"),
        applying=applying,
    )


def _pattern_from_dict(value: Any, index: int) -> PatternHit:
    name = f"patterns[{index}]"
    item = _mapping(value, name)
    return PatternHit(
        pattern_id=_required_string(item, "pattern_id"),
        members=_string_tuple(item.get("members"), f"{name}.members"),
        sign=_optional_string(item.get("sign"), f"{name}.sign"),
        apex=_optional_string(item.get("apex"), f"{name}.apex"),
    )


def _meta_aspect_rules(value: Any) -> tuple[tuple[str, float, float], ...]:
    rows = _list(value, "meta.aspect_rules")
    result: list[tuple[str, float, float]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 3:
            raise ChartLibraryError(
                f"Saved meta.aspect_rules[{index}] must be a three-item list"
            )
        result.append(
            (
                _required_list_string(row[0], f"meta.aspect_rules[{index}][0]"),
                _finite_float(row[1], f"meta.aspect_rules[{index}][1]"),
                _finite_float(row[2], f"meta.aspect_rules[{index}][2]"),
            )
        )
    return tuple(result)


def _read_chart_file(path: Path) -> SavedChart:
    if path.is_symlink():
        raise ChartLibraryError(f"Refusing to read symlinked chart file: {path}")
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: _reject_json_constant(value, path),
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ChartLibraryError(f"Could not read saved chart {path}: {exc}") from exc
    record = _record_from_payload(payload, path)
    if record.id != path.stem:
        raise ChartLibraryError(
            f"Saved chart id {record.id!r} does not match filename {path.name!r}"
        )
    return record


def _record_from_payload(payload: Any, path: Path) -> SavedChart:
    if not isinstance(payload, Mapping):
        raise ChartLibraryError(f"Saved chart {path} must contain a JSON object")
    if payload.get("schema_version") != SAVED_CHART_SCHEMA_VERSION:
        raise ChartLibraryError(
            f"Unsupported saved chart schema_version in {path}: {payload.get('schema_version')!r}"
        )
    chart_id = _required_string(payload, "id")
    if not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*-\d{8}T\d{6}(?:\d{6})?Z-[0-9a-f]{10}",
        chart_id,
    ):
        raise ChartLibraryError(f"Invalid saved chart id: {chart_id!r}")
    label = _string(payload.get("label", ""), "label")
    local_datetime = _required_string(payload, "local_datetime")
    try:
        parsed_local_datetime = datetime.fromisoformat(local_datetime)
    except ValueError as exc:
        raise ChartLibraryError(f"Invalid saved local_datetime: {exc}") from exc
    if parsed_local_datetime.tzinfo is None:
        raise ChartLibraryError("Saved local_datetime must be timezone-aware")
    tz = _required_string(payload, "tz")

    systems_payload = payload.get("systems")
    if not isinstance(systems_payload, list):
        raise ChartLibraryError("Saved systems must be a list")
    systems = tuple(_required_list_string(item, "systems") for item in systems_payload)
    if not systems or len(set(systems)) != len(systems):
        raise ChartLibraryError("Saved systems must be a non-empty list without duplicates")

    input_payload = payload.get("input")
    config_payload = payload.get("config")
    chart_payload = payload.get("chart")
    if not isinstance(input_payload, Mapping):
        raise ChartLibraryError("Saved input must be an object")
    if not isinstance(config_payload, Mapping):
        raise ChartLibraryError("Saved config must be an object")
    if not isinstance(chart_payload, Mapping):
        raise ChartLibraryError("Saved chart geometry must be an object")
    moment = moment_from_dict(input_payload)
    config = config_from_dict(config_payload)
    if moment.label != label or moment.tz != tz:
        raise ChartLibraryError("Saved summary metadata does not match its input")
    meta = chart_payload.get("meta")
    if not isinstance(meta, Mapping) or meta.get("input") != input_payload:
        raise ChartLibraryError("Saved geometry metadata does not match its input")
    if meta.get("local_datetime") != local_datetime:
        raise ChartLibraryError("Saved geometry local datetime does not match its summary")
    if meta.get("zodiac_system") != config.zodiac:
        raise ChartLibraryError("Saved geometry zodiac does not match its configuration")
    if systems[0] != config.zodiac:
        raise ChartLibraryError("Saved systems must list the primary zodiac first")

    report_path = payload.get("last_report_path")
    if report_path is not None:
        report_path = _path_string(report_path, "last_report_path")
    return SavedChart(
        id=chart_id,
        label=label,
        local_datetime=local_datetime,
        tz=tz,
        systems=systems,
        input=dict(input_payload),
        config=dict(config_payload),
        chart=dict(chart_payload),
        last_report_path=report_path,
        source_path=path,
    )


def _normalize_systems(
    systems: Iterable[str] | None,
    primary: str,
) -> tuple[str, ...]:
    result = [primary]
    if systems is not None:
        for value in systems:
            system = _required_list_string(value, "systems")
            if system not in result:
                result.append(system)
    return tuple(result)


def _require_one_label(
    identifier: str,
    matches: tuple[SavedChart, ...],
) -> SavedChart:
    if len(matches) == 1:
        return matches[0]
    ids = ", ".join(item.id for item in matches)
    raise AmbiguousChartError(
        f"Saved chart label {identifier!r} is ambiguous; use one of these ids: {ids}"
    )


def _slugify(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return slug[:_SLUG_LIMIT].rstrip("-") or "chart"


def _utc_token(value: datetime) -> str:
    if value.tzinfo is None:
        raise ChartLibraryError("Chart UTC datetime must be timezone-aware")
    instant = value.astimezone(UTC)
    token = (
        f"{instant.year:04d}{instant.month:02d}{instant.day:02d}T"
        f"{instant.hour:02d}{instant.minute:02d}{instant.second:02d}"
    )
    if instant.microsecond:
        token += f"{instant.microsecond:06d}"
    return token + "Z"


def _record_fingerprint(
    input_payload: Mapping[str, Any],
    config_payload: Mapping[str, Any],
) -> str:
    encoded = json.dumps(
        {"input": input_payload, "config": config_payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:10]


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():  # pragma: no cover - mkdir generally raises first
        raise ChartLibraryError(f"Charts path is not a directory: {path}")
    try:
        path.chmod(0o700)
    except OSError:  # pragma: no cover - platforms without POSIX mode support
        pass


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:  # pragma: no cover - platforms without POSIX modes
            pass
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    if key not in payload:
        raise ChartLibraryError(f"Saved record is missing {key!r}")
    value = _string(payload[key], key)
    if not value.strip():
        raise ChartLibraryError(f"Saved {key} must not be empty")
    return value


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    if key not in payload:
        raise ChartLibraryError(f"Saved record is missing {key!r}")
    return _mapping(payload[key], key)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ChartLibraryError(f"Saved {name} must be an object")
    return value


def _required_list(payload: Mapping[str, Any], key: str) -> list[Any]:
    if key not in payload:
        raise ChartLibraryError(f"Saved record is missing {key!r}")
    return _list(payload[key], key)


def _list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ChartLibraryError(f"Saved {name} must be a list")
    return value


def _required_list_string(value: Any, name: str) -> str:
    result = _string(value, name)
    if not result.strip():
        raise ChartLibraryError(f"Saved {name} values must not be empty")
    return result


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ChartLibraryError(f"Saved {name} must be a string")
    return value


def _optional_string(value: Any, name: str) -> str | None:
    return None if value is None else _string(value, name)


def _string_tuple(value: Any, name: str) -> tuple[str, ...]:
    return tuple(
        _required_list_string(item, f"{name}[{index}]")
        for index, item in enumerate(_list(value, name))
    )


def _aware_datetime(value: Any, name: str) -> datetime:
    raw = _string(value, name)
    try:
        result = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ChartLibraryError(f"Invalid saved {name}: {exc}") from exc
    if result.tzinfo is None:
        raise ChartLibraryError(f"Saved {name} must be timezone-aware")
    return result


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ChartLibraryError(f"Saved {name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ChartLibraryError(f"Saved {name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ChartLibraryError(f"Saved {name} must be a finite number")
    return result


def _optional_finite_float(value: Any, name: str) -> float | None:
    return None if value is None else _finite_float(value, name)


def _integer(
    value: Any,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ChartLibraryError(f"Saved {name} must be an integer")
    if minimum is not None and value < minimum:
        raise ChartLibraryError(f"Saved {name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ChartLibraryError(f"Saved {name} must be at most {maximum}")
    return value


def _optional_integer(
    value: Any,
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if value is None:
        return None
    return _integer(value, name, minimum=minimum, maximum=maximum)


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ChartLibraryError(f"Saved {name} must be a boolean")
    return value


def _optional_path(value: Any, name: str) -> Path | None:
    if value is None:
        return None
    return Path(_path_string(value, name))


def _path_string(value: Any, name: str) -> str:
    result = _string(value, name)
    if not result.strip() or "\x00" in result:
        raise ChartLibraryError(f"Saved {name} must be a valid non-empty path")
    return result


def _reject_json_constant(value: str, path: Path) -> None:
    raise ChartLibraryError(f"Saved chart {path} contains non-standard JSON value {value}")


def _json_copy(value: Any) -> Any:
    return json.loads(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    )


__all__ = [
    "AmbiguousChartError",
    "ChartLibraryError",
    "ChartNotFoundError",
    "DEFAULT_CHARTS_DIR",
    "SAVED_CHART_SCHEMA_VERSION",
    "SavedChart",
    "chart_from_dict",
    "config_from_dict",
    "config_to_dict",
    "list_charts",
    "load_chart",
    "moment_from_dict",
    "moment_to_dict",
    "save_chart",
    "update_last_report_path",
]
