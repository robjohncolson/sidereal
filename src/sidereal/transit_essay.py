"""Private daily transit-to-natal facts and asynchronous symbolic essays."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import sqlite3
from threading import Condition, RLock, Thread
from typing import Any, Protocol

from .aspects import shortest_arc
from .auth import normalize_user_id
from .chart import compute
from .config import ASPECT_POINT_IDS, BODY_IDS
from .ephemeris import EphemerisError
from .interpret.ai_seed import (
    BANNED_GENERATED_FRAGMENTS,
    DeepSeekConfig,
    DeepSeekRequestError,
    DeepSeekTransport,
    UrllibDeepSeekTransport,
)
from .interpret.schema import InterpretationEntry, aspect_key
from .interpret.store import InterpretationStoreError
from .natal import NatalRecord
from .personal_sky import compute_natal_chart
from .timebase import parse_timezone
from .transit import compute_transit_geometry
from .types import MomentInput


TRANSIT_ESSAY_SCHEMA_VERSION = 1
TRANSIT_ESSAY_TYPE = "personal_transit_essay"
TRANSIT_ESSAY_FACTS_TYPE = "transit_essay_facts"
TRANSIT_ESSAY_MAX_ASPECTS = 24
TRANSIT_ESSAY_EPISTEMIC = "symbolic study notes, not predictions"
SKY_BRIEF_EPISTEMIC = (
    "Symbolic study notes, not predictions. "
    "Not medical, legal, or financial advice."
)
TRANSIT_ESSAY_SYSTEM_PROMPT = """You author one private daily transit study for Sidereal.
Use the Midpoint 13-sign symbolic framework and treat Ophiuchus as a first-class sign.
Synthesize only the geometry and catalog notes in the supplied fact object. Never invent or imply an aspect that is absent from its aspects array.
You may speak naturally about squares, trines, and other major aspects. Prefer concrete pairings grounded in the facts (e.g. “Transit Mars square natal Moon”). Never invent a pairing absent from the aspects array.
Use tentative, reflective language rather than personality verdicts or event forecasts.
Do not make medical, diagnostic, treatment, financial, legal, crisis, death, fate, or guaranteed-outcome claims.
Return only one JSON object with exactly these fields: headline (string), body (string), watchpoints (array of strings).
Keep the headline at most 120 characters, the body concise and coherent, and watchpoints to five or fewer reflective observations.
Do not use HTML, Markdown fences, or commentary outside the JSON object."""

_ESSAY_GENERATED_FIELDS = frozenset(("headline", "body", "watchpoints"))
_ESSAY_STATUSES = frozenset(("pending", "ready", "failed"))
_ESSAY_SOURCE = "ai-deepseek"
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
_TRANSIT_ESSAY_BANNED_FRAGMENTS = frozenset(
    (
        *BANNED_GENERATED_FRAGMENTS,
        "will happen",
        "will bring",
        "guarantee",
        "medical",
        "financial",
        "legal",
        "fated",
        "destined",
        "fated to",
        "fate guarantees",
        "destiny guarantees",
        "guarantee that",
    )
)
_BODY_REFERENCE_PATTERN = (
    r"sun|moon|mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto|"
    r"north[ _-]?node|south[ _-]?node|ascendant|midheaven|asc|mc"
)
_ASPECT_REFERENCE_PATTERN = (
    r"conjunct(?:ion|s)?|oppos(?:ition|ite|es)|trin(?:e|es)|"
    r"squar(?:e|es)|sextil(?:e|es)"
)
_FORMAL_ASPECT_RE = re.compile(
    rf"\b(?:transit(?:ing)?\s+)?(?P<transit>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:(?:is|was)\s+|(?:forms?|makes?)\s+(?:an?\s+)?)?"
    rf"(?P<aspect>{_ASPECT_REFERENCE_PATTERN})\s+"
    rf"(?:to\s+|with\s+)?(?:your\s+|the\s+)?(?:natal\s+)?"
    rf"(?P<natal>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_PAIR_ASPECT_RE = re.compile(
    rf"\b(?:transit(?:ing)?\s+)?(?P<transit>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:and|with)\s+(?:your\s+|the\s+)?(?:natal\s+)?"
    rf"(?P<natal>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:forms?|makes?)\s+(?:an?\s+)?"
    rf"(?P<aspect>{_ASPECT_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_ASPECT_LEXEME_RE = re.compile(
    rf"\b(?:{_ASPECT_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_LOGGER = logging.getLogger(__name__)


class TransitEssayError(RuntimeError):
    """Base error for private transit essay work."""


class TransitEssayValidationError(TransitEssayError, ValueError):
    """A fact, generated object, or essay key failed validation."""


class TransitEssayStoreError(TransitEssayError):
    """Private essay persistence could not complete an operation."""


class InterpretationLookup(Protocol):
    def get(self, entry_id: str) -> InterpretationEntry | None:
        ...


@dataclass(frozen=True, slots=True)
class GeneratedTransitEssay:
    """Validated provider fields before private record metadata is attached."""

    headline: str
    body: str
    watchpoints: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "body": self.body,
            "watchpoints": list(self.watchpoints),
        }


@dataclass(frozen=True, slots=True)
class TransitEssayRecord:
    """One fingerprinted per-user civil-day essay state."""

    user_id: str
    cache_date: str
    natal_fingerprint: str
    status: str
    headline: str = ""
    body: str = ""
    watchpoints: tuple[str, ...] = ()
    epistemic: str = TRANSIT_ESSAY_EPISTEMIC
    model: str = ""
    source: str = ""
    generated_at: datetime | None = None

    def __post_init__(self) -> None:
        _essay_key(self.user_id, self.cache_date, self.natal_fingerprint)
        if self.status not in _ESSAY_STATUSES:
            raise ValueError(f"invalid transit essay status: {self.status!r}")
        for name in ("headline", "body", "epistemic", "model", "source"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"{name} must be a string")
        if not isinstance(self.watchpoints, tuple) or any(
            not isinstance(item, str) for item in self.watchpoints
        ):
            raise ValueError("watchpoints must be a tuple of strings")
        if self.status == "ready":
            if not self.headline or not self.body or not self.model or not self.source:
                raise ValueError("ready transit essays require generated content metadata")
            if self.generated_at is None or self.generated_at.tzinfo is None:
                raise ValueError("ready transit essays require an aware generated_at")
        elif self.generated_at is not None:
            raise ValueError("only ready transit essays may have generated_at")

    def to_api_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": TRANSIT_ESSAY_SCHEMA_VERSION,
            "type": TRANSIT_ESSAY_TYPE,
            "status": self.status,
            "cache_date": self.cache_date,
        }
        if self.status == "ready":
            assert self.generated_at is not None
            result.update(
                headline=self.headline,
                body=self.body,
                watchpoints=list(self.watchpoints),
                epistemic=self.epistemic,
                model=self.model,
                source=self.source,
                generated_at=_utc_isoformat(self.generated_at),
            )
        elif self.status == "failed":
            result["detail"] = "Transit essay generation failed."
        return result


def natal_fingerprint(record: NatalRecord) -> str:
    """Hash private natal metadata for cache invalidation without exposing it."""

    if not isinstance(record, NatalRecord):
        raise TypeError("record must be a NatalRecord")
    payload = {
        "birth_date": record.birth_date.isoformat(),
        "birth_time": (
            record.birth_time.isoformat() if record.birth_time is not None else None
        ),
        "time_unknown": record.time_unknown,
        "tz": record.tz,
        "lat": record.lat,
        "lon": record.lon,
    }
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def transit_essay_cache_date(record: NatalRecord, when: datetime) -> str:
    """Resolve the authenticated user's civil date for one aware instant."""

    if not isinstance(record, NatalRecord):
        raise TypeError("record must be a NatalRecord")
    instant = _aware_utc(when, "when")
    return instant.astimezone(parse_timezone(record.tz)).date().isoformat()


def build_transit_essay_facts(
    record: NatalRecord,
    *,
    when: datetime | None = None,
    store: InterpretationLookup | None = None,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
    max_aspects: int = TRANSIT_ESSAY_MAX_ASPECTS,
) -> dict[str, Any]:
    """Build a complete, visibility-independent transit-to-natal fact payload."""

    if not isinstance(record, NatalRecord):
        raise TypeError("record must be a NatalRecord")
    if (
        not isinstance(max_aspects, int)
        or isinstance(max_aspects, bool)
        or max_aspects <= 0
    ):
        raise ValueError("max_aspects must be a positive integer")
    instant = _aware_utc(
        when or datetime.now(UTC).replace(microsecond=0),
        "when",
    )
    natal_chart, natal_config = compute_natal_chart(
        record,
        boundary_path=boundary_path,
        ephe_path=ephe_path,
        require_swiss_ephemeris=require_swiss_ephemeris,
    )
    transit_config = _transit_config(natal_config)
    transit_moment = MomentInput(
        local_date=instant.date(),
        local_time=instant.timetz().replace(tzinfo=None),
        tz="UTC",
        label="Transit essay sky",
    )
    transit_chart = compute(transit_moment, transit_config)
    geometry = compute_transit_geometry(
        natal_chart,
        transit_chart,
        transit_config,
    )

    natal_placements = [
        _point_fact(point)
        for point in geometry.natal.points
        if point.kind == "body" or point.id in {"asc", "mc"}
    ]
    movers = [
        {
            "body": placement.id,
            "sign": placement.sign,
            "degree_in_sign": _fact_number(placement.degree_in_sign),
            "retro": bool(placement.retro),
            **(
                {"natal_house": placement.natal_house}
                if placement.natal_house is not None
                else {}
            ),
        }
        for placement in geometry.placements
    ]
    natal_bodies = {
        point.id: point
        for point in geometry.natal.points
        if point.kind == "body" and point.id in BODY_IDS
    }
    transit_bodies = {
        point.id: point
        for point in geometry.transit.points
        if point.kind == "body" and point.id in BODY_IDS
    }
    same_body_delta = [
        {
            "body": body,
            "delta_deg": _fact_number(
                shortest_arc(
                    transit_bodies[body].lon_j2000,
                    natal_bodies[body].lon_j2000,
                )
            ),
        }
        for body in BODY_IDS
        if body in transit_bodies and body in natal_bodies
    ]

    ranked_hits = sorted(
        geometry.aspects,
        key=lambda hit: (
            hit.exactness / hit.orb_used,
            hit.exactness,
            hit.transit_body,
            hit.natal_point,
            hit.aspect_id,
        ),
    )[:max_aspects]
    aspects = [
        _aspect_fact(hit, store)
        for hit in ranked_hits
    ]
    return {
        "schema_version": TRANSIT_ESSAY_SCHEMA_VERSION,
        "type": TRANSIT_ESSAY_FACTS_TYPE,
        "cache_date": transit_essay_cache_date(record, instant),
        "timezone": record.tz,
        "epoch_utc": _utc_isoformat(geometry.transit.meta.utc_datetime),
        "natal": {
            "time_unknown": record.time_unknown,
            "tz": record.tz,
            "placements": natal_placements,
        },
        "sky": {"movers": movers},
        "same_body_delta": same_body_delta,
        "aspects": aspects,
    }


def format_sky_brief_text(
    facts: Mapping[str, Any],
    essay: Mapping[str, Any] | TransitEssayRecord | GeneratedTransitEssay | None = None,
) -> str:
    """Render the private daily fact projection as canonical plain text.

    Only the explicitly documented fact fields are read. Private natal metadata
    such as coordinates, user identifiers, e-mail addresses, and place labels
    therefore cannot leak through incidental keys in ``facts``.
    """

    if not isinstance(facts, Mapping):
        raise TypeError("facts must be a mapping")
    cache_date = _brief_required_text(facts.get("cache_date"), "facts.cache_date")
    timezone = _brief_required_text(facts.get("timezone"), "facts.timezone")
    epoch_utc = _brief_required_text(facts.get("epoch_utc"), "facts.epoch_utc")

    natal = _brief_mapping(facts.get("natal"))
    sky = _brief_mapping(facts.get("sky"))
    lines = [
        "# Moon Chorus sky brief",
        f"date: {cache_date} ({timezone})",
        f"epoch_utc: {epoch_utc}",
        "frame: sidereal / 13-sign midpoints (as product already uses)",
        f"epistemic: {SKY_BRIEF_EPISTEMIC}",
        "",
        "## Natal placements",
    ]
    natal_placements = _brief_items(natal.get("placements"))
    if natal_placements:
        for placement in natal_placements:
            parts = [
                _brief_display(placement.get("body")),
                _brief_display(placement.get("sign")),
                _brief_degree(placement.get("degree_in_sign")),
            ]
            if placement.get("retro") is True:
                parts.append("Rx")
            house = _brief_house(placement.get("house"))
            if house is not None:
                parts.append(f"house {house}")
            lines.append(" · ".join(parts))
    else:
        lines.append("No natal placements available.")
    if natal.get("time_unknown") is True:
        lines.append(
            "Time unknown · houses and angles may be omitted or marked uncertain."
        )

    lines.extend(("", "## Today’s movers (transit)"))
    movers = _brief_items(sky.get("movers"))
    if movers:
        for mover in movers:
            parts = [
                _brief_display(mover.get("body")),
                _brief_display(mover.get("sign")),
                _brief_degree(mover.get("degree_in_sign")),
            ]
            if mover.get("retro") is True:
                parts.append("Rx")
            natal_house = _brief_house(mover.get("natal_house"))
            if natal_house is not None:
                parts.append(f"natal house {natal_house}")
            lines.append(" · ".join(parts))
    else:
        lines.append("No transit movers available.")

    lines.extend(("", "## Transit → natal contacts"))
    aspects = _brief_items(facts.get("aspects"))
    if aspects:
        for aspect in aspects:
            applying = aspect.get("applying")
            motion = _brief_motion(applying, aspect.get("orb"))
            lines.append(
                "Transit "
                f"{_brief_display(aspect.get('transit_body'))} "
                f"{_brief_display(aspect.get('aspect_id')).casefold()} "
                f"natal {_brief_display(aspect.get('natal_point'))} · "
                f"orb {_brief_degree(aspect.get('orb'))} · {motion}"
            )
    else:
        lines.append("No ranked transit contacts available.")

    same_body_deltas = _brief_items(facts.get("same_body_delta"))
    if same_body_deltas:
        lines.extend(("", "## Same-body deltas (optional short list)"))
        for item in same_body_deltas:
            lines.append(
                f"{_brief_display(item.get('body'))} · transit vs natal separation "
                f"{_brief_degree(item.get('delta_deg'))}"
            )

    essay_payload = _brief_essay_payload(essay)
    if essay_payload is not None:
        lines.extend(
            (
                "",
                "## Today’s sky note",
                f"headline: {essay_payload['headline']}",
                "body:",
                essay_payload["body"],
                "watchpoints:",
            )
        )
        watchpoints = essay_payload["watchpoints"]
        if watchpoints:
            lines.extend(f"- {item}" for item in watchpoints)

    return "\n".join(lines).rstrip() + "\n"


def _brief_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _brief_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _brief_required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TransitEssayValidationError(f"{name} must be a non-empty string")
    result = value.strip()
    if any(character in result for character in "\r\n\x00"):
        raise TransitEssayValidationError(f"{name} must be a single line")
    return result


def _brief_display(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Unknown"
    identifier = re.sub(r"\s+", " ", value.strip().replace("_", " "))
    special = {"asc": "Ascendant", "mc": "Midheaven"}
    return special.get(identifier.casefold(), identifier.title())


def _brief_degree(value: Any) -> str:
    number = _brief_finite_number(value, "sky brief degree")
    if abs(number) < 0.05:
        number = 0.0
    return f"{number:.1f}°"


def _brief_finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise TransitEssayValidationError(f"{name} must be finite")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TransitEssayValidationError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise TransitEssayValidationError(f"{name} must be finite")
    return number


def _brief_motion(applying: Any, orb: Any) -> str:
    if abs(_brief_finite_number(orb, "sky brief orb")) <= 1e-10:
        return "exact"
    if applying is True:
        return "applying"
    if applying is False:
        return "separating"
    return "motion indeterminate"


def _brief_house(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TransitEssayValidationError("sky brief house must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise TransitEssayValidationError("sky brief house must be an integer") from exc
    if number != value or not 1 <= number <= 12:
        raise TransitEssayValidationError("sky brief house must be from 1 through 12")
    return number


def _brief_essay_payload(
    essay: Mapping[str, Any] | TransitEssayRecord | GeneratedTransitEssay | None,
) -> dict[str, Any] | None:
    if essay is None:
        return None
    if isinstance(essay, TransitEssayRecord):
        if essay.status != "ready":
            return None
        payload: Mapping[str, Any] = essay.to_api_dict()
    elif isinstance(essay, GeneratedTransitEssay):
        payload = essay.to_dict()
    elif isinstance(essay, Mapping):
        payload = essay
    else:
        raise TypeError("essay must be a mapping or transit essay record")
    if payload.get("status") not in (None, "ready"):
        return None

    headline = _brief_multiline_text(payload.get("headline"), "essay.headline")
    body = _brief_multiline_text(payload.get("body"), "essay.body")
    headline = " ".join(headline.splitlines())
    raw_watchpoints = payload.get("watchpoints", ())
    if not isinstance(raw_watchpoints, (list, tuple)) or any(
        not isinstance(item, str) for item in raw_watchpoints
    ):
        raise TransitEssayValidationError("essay.watchpoints must be an array")
    watchpoints = tuple(
        " ".join(_brief_multiline_text(item, "essay.watchpoint").splitlines())
        for item in raw_watchpoints
    )
    return {"headline": headline, "body": body, "watchpoints": watchpoints}


def _brief_multiline_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TransitEssayValidationError(f"{name} must be a non-empty string")
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()


def validate_transit_essay_content(
    payload: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> GeneratedTransitEssay:
    """Validate exact provider fields, safety language, and formal aspect claims."""

    if not isinstance(payload, Mapping):
        raise TransitEssayValidationError("transit essay must be a JSON object")
    fields = frozenset(payload)
    missing = sorted(_ESSAY_GENERATED_FIELDS - fields)
    extra = sorted(fields - _ESSAY_GENERATED_FIELDS)
    if missing:
        raise TransitEssayValidationError(
            f"transit essay is missing field(s): {', '.join(missing)}"
        )
    if extra:
        raise TransitEssayValidationError(
            f"transit essay has unsupported field(s): {', '.join(extra)}"
        )
    headline = _essay_text(payload.get("headline"), "headline", 1, 120)
    body = _essay_text(payload.get("body"), "body", 80, 4_000)
    raw_watchpoints = payload.get("watchpoints")
    if not isinstance(raw_watchpoints, list):
        raise TransitEssayValidationError("watchpoints must be an array")
    if len(raw_watchpoints) > 5:
        raise TransitEssayValidationError("watchpoints must contain at most 5 items")
    watchpoints: list[str] = []
    seen: set[str] = set()
    for value in raw_watchpoints:
        item = _essay_text(value, "watchpoint", 1, 240)
        identity = item.casefold()
        if identity in seen:
            raise TransitEssayValidationError("watchpoints must be unique")
        seen.add(identity)
        watchpoints.append(item)
    all_text = (headline, body, *watchpoints)
    for value in all_text:
        if "<" in value or ">" in value:
            raise TransitEssayValidationError("transit essay must not contain HTML")
        normalized = re.sub(r"\s+", " ", value.casefold())
        banned = next(
            (
                fragment
                for fragment in _TRANSIT_ESSAY_BANNED_FRAGMENTS
                if fragment in normalized
            ),
            None,
        )
        if banned is not None:
            raise TransitEssayValidationError(
                f"transit essay contains banned fragment {banned!r}"
            )
    # Formal aspect-pair auditing was removed as a hard gate: models naturally
    # paraphrase contacts, and rejecting those failed the whole daily essay.
    # The system prompt still forbids inventing geometry; banned-phrase + schema
    # remain the hard validators.
    return GeneratedTransitEssay(
        headline=headline,
        body=body,
        watchpoints=tuple(watchpoints),
    )


def _transit_config(value: Any) -> Any:
    from dataclasses import replace

    result = replace(value, include_houses=False, include_patterns=False)
    result.validate()
    return result


def _point_fact(point: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "body": point.id,
        "sign": point.sign,
        "degree_in_sign": _fact_number(point.degree_in_sign),
    }
    if point.kind == "body":
        result["retro"] = bool(point.retro)
    if point.house is not None:
        result["house"] = int(point.house)
    return result


def _aspect_fact(hit: Any, store: InterpretationLookup | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "transit_body": hit.transit_body,
        "natal_point": hit.natal_point,
        "aspect_id": hit.aspect_id,
        "separation": _fact_number(hit.separation),
        "orb": _fact_number(hit.exactness),
        "orb_limit": _fact_number(hit.orb_used),
        "applying": hit.applying,
    }
    entry: InterpretationEntry | None = None
    if store is not None:
        try:
            entry = store.get(
                aspect_key(hit.transit_body, hit.aspect_id, hit.natal_point)
            )
        except ValueError:
            entry = None
    result["seed_status"] = "missing" if entry is None else entry.status
    if entry is not None and entry.status == "ready":
        summary = entry.summary.strip()
        if summary:
            result["seed_summary"] = _truncate(summary, 500)
    return result


def _fact_number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise TransitEssayValidationError("transit essay facts must be finite")
    return round(result, 6)


def _essay_text(value: Any, name: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise TransitEssayValidationError(f"{name} must be a string")
    normalized = value.strip()
    if len(normalized) < minimum:
        raise TransitEssayValidationError(
            f"{name} must contain at least {minimum} characters"
        )
    if len(normalized) > maximum:
        raise TransitEssayValidationError(
            f"{name} must contain at most {maximum} characters"
        )
    return normalized


def _validate_formal_aspect_references(
    values: tuple[str, ...],
    facts: Mapping[str, Any],
) -> None:
    """Reject concrete body–aspect–body claims that are absent from facts.

    Natural language may use words like ``square`` or ``trine`` freely. Only
    *pair claims* (Transit Mars square natal Moon, etc.) are checked against
    the fact list so the model cannot invent specific contacts.
    """

    raw_aspects = facts.get("aspects") if isinstance(facts, Mapping) else None
    if not isinstance(raw_aspects, list):
        raise TransitEssayValidationError("transit essay facts require an aspects array")
    allowed = {
        (
            str(item.get("transit_body") or ""),
            str(item.get("aspect_id") or ""),
            str(item.get("natal_point") or ""),
        )
        for item in raw_aspects
        if isinstance(item, Mapping)
    }
    for value in values:
        matches = tuple(
            (
                *_FORMAL_ASPECT_RE.finditer(value),
                *_PAIR_ASPECT_RE.finditer(value),
            )
        )
        for match in matches:
            claim = (
                _normalized_body_reference(match.group("transit")),
                _normalized_aspect_reference(match.group("aspect")),
                _normalized_body_reference(match.group("natal")),
            )
            if claim not in allowed:
                raise TransitEssayValidationError(
                    "transit essay mentions an aspect absent from the facts"
                )


def _normalized_body_reference(value: str) -> str:
    normalized = re.sub(r"[ -]+", "_", value.casefold())
    return {"ascendant": "asc", "midheaven": "mc"}.get(normalized, normalized)


def _normalized_aspect_reference(value: str) -> str:
    normalized = value.casefold()
    if normalized.startswith("conjunct"):
        return "conjunction"
    if normalized.startswith("opposit"):
        return "opposition"
    if normalized.startswith("trin"):
        return "trine"
    if normalized.startswith("squar"):
        return "square"
    if normalized.startswith("sextil"):
        return "sextile"
    return normalized


def _truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: maximum - 1].rstrip() + "…"


class TransitEssayAuthor(Protocol):
    @property
    def model(self) -> str:
        ...

    def generate(self, facts: Mapping[str, Any]) -> GeneratedTransitEssay:
        ...


class DeepSeekTransitEssayAuthor:
    """Strict DeepSeek JSON author whose user message is the fact payload only."""

    def __init__(
        self,
        config: DeepSeekConfig,
        *,
        transport: DeepSeekTransport | None = None,
    ) -> None:
        if not isinstance(config, DeepSeekConfig):
            raise TypeError("config must be a DeepSeekConfig")
        self._config = config
        self._transport = transport or UrllibDeepSeekTransport()

    @property
    def model(self) -> str:
        return self._config.model

    @classmethod
    def from_env(cls) -> DeepSeekTransitEssayAuthor:
        return cls(DeepSeekConfig.from_env())

    def generate(self, facts: Mapping[str, Any]) -> GeneratedTransitEssay:
        if not isinstance(facts, Mapping):
            raise TypeError("facts must be a mapping")
        user_content = json.dumps(
            dict(facts),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": TRANSIT_ESSAY_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0.4,
            "max_tokens": 1600,
            "stream": False,
        }
        response = self._transport.post_json(
            self._config.endpoint,
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            payload=payload,
            timeout_seconds=self._config.timeout_seconds,
        )
        choices = response.get("choices") if isinstance(response, Mapping) else None
        if not isinstance(choices, list) or not choices:
            raise DeepSeekRequestError("DeepSeek returned no transit essay choice")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise DeepSeekRequestError("DeepSeek returned an invalid transit essay choice")
        finish_reason = choice.get("finish_reason")
        # Accept normal completion or length-capped JSON if still parseable.
        if finish_reason not in {None, "stop", "length"}:
            raise DeepSeekRequestError("DeepSeek transit essay did not finish cleanly")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekRequestError("DeepSeek returned an empty transit essay")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned, count=1)
        try:
            decoded = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise DeepSeekRequestError("DeepSeek transit essay was not valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise DeepSeekRequestError("DeepSeek transit essay JSON must be an object")
        return validate_transit_essay_content(decoded, facts)


class TransitEssayStore(Protocol):
    def get(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord | None:
        ...

    def ensure_pending(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord:
        ...

    def mark_ready(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        content: GeneratedTransitEssay,
        *,
        model: str,
        generated_at: datetime,
    ) -> TransitEssayRecord:
        ...

    def mark_failed(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord:
        ...

    def delete_user(self, user_id: str) -> None:
        ...

    def delete_key(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> None:
        ...


class MemoryTransitEssayStore:
    """Thread-safe process cache for private essay states."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, str], TransitEssayRecord] = {}
        self._lock = RLock()

    def get(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord | None:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            return self._records.get(key)

    def ensure_pending(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            current = self._records.get(key)
            if current is not None:
                return current
            record = TransitEssayRecord(*key, status="pending")
            self._records[key] = record
            return record

    def mark_ready(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        content: GeneratedTransitEssay,
        *,
        model: str,
        generated_at: datetime,
    ) -> TransitEssayRecord:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        if not isinstance(content, GeneratedTransitEssay):
            raise TypeError("content must be GeneratedTransitEssay")
        record = TransitEssayRecord(
            *key,
            status="ready",
            headline=content.headline,
            body=content.body,
            watchpoints=content.watchpoints,
            model=_required_text(model, "model"),
            source=_ESSAY_SOURCE,
            generated_at=_aware_utc(generated_at, "generated_at"),
        )
        with self._lock:
            current = self._records.get(key)
            if current is None or current.status != "pending":
                raise TransitEssayStoreError("transit essay pending record disappeared")
            self._records[key] = record
            while len(self._records) > 2_048:
                self._records.pop(next(iter(self._records)))
        return record

    def mark_failed(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        record = TransitEssayRecord(*key, status="failed")
        with self._lock:
            current = self._records.get(key)
            if current is None or current.status != "pending":
                raise TransitEssayStoreError("transit essay pending record disappeared")
            self._records[key] = record
        return record

    def delete_user(self, user_id: str) -> None:
        normalized = normalize_user_id(user_id)
        with self._lock:
            for key in tuple(self._records):
                if key[0] == normalized:
                    self._records.pop(key, None)

    def delete_key(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> None:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            self._records.pop(key, None)

    def close(self) -> None:
        return None


_ESSAY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS personal_transit_essays (
    user_id TEXT NOT NULL,
    cache_date TEXT NOT NULL,
    natal_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'ready', 'failed')),
    headline TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    watchpoints_json TEXT NOT NULL DEFAULT '[]',
    epistemic TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    generated_at TEXT,
    PRIMARY KEY (user_id, cache_date, natal_fingerprint)
);
CREATE INDEX IF NOT EXISTS personal_transit_essays_user_date_idx
ON personal_transit_essays(user_id, cache_date);
"""


class SQLiteTransitEssayStore:
    """Lazy SQLite persistence compatible with the interpretation volume DB."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self._connection: sqlite3.Connection | None = None
        self._lock = RLock()
        self._closed = False

    def _connect(self) -> sqlite3.Connection:
        if self._closed:
            raise TransitEssayStoreError("Transit essay storage is closed")
        if self._connection is not None:
            return self._connection
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                connection.executescript(_ESSAY_TABLE_SQL)
        except sqlite3.Error as exc:
            raise TransitEssayStoreError("Transit essay storage is unavailable") from exc
        self._connection = connection
        return connection

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def get(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord | None:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            try:
                row = self._connect().execute(
                    "SELECT * FROM personal_transit_essays "
                    "WHERE user_id = ? AND cache_date = ? AND natal_fingerprint = ?",
                    key,
                ).fetchone()
            except sqlite3.Error as exc:
                raise TransitEssayStoreError(
                    "Transit essay storage is unavailable"
                ) from exc
        return None if row is None else self._row_to_record(row)

    def ensure_pending(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        pending = TransitEssayRecord(*key, status="pending")
        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    connection.execute(
                        "INSERT OR IGNORE INTO personal_transit_essays "
                        "(user_id, cache_date, natal_fingerprint, status, epistemic) "
                        "VALUES (?, ?, ?, 'pending', ?)",
                        (*key, TRANSIT_ESSAY_EPISTEMIC),
                    )
                row = connection.execute(
                    "SELECT * FROM personal_transit_essays "
                    "WHERE user_id = ? AND cache_date = ? AND natal_fingerprint = ?",
                    key,
                ).fetchone()
            except sqlite3.Error as exc:
                raise TransitEssayStoreError(
                    "Transit essay storage is unavailable"
                ) from exc
        return pending if row is None else self._row_to_record(row)

    def mark_ready(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        content: GeneratedTransitEssay,
        *,
        model: str,
        generated_at: datetime,
    ) -> TransitEssayRecord:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        if not isinstance(content, GeneratedTransitEssay):
            raise TypeError("content must be GeneratedTransitEssay")
        record = TransitEssayRecord(
            *key,
            status="ready",
            headline=content.headline,
            body=content.body,
            watchpoints=content.watchpoints,
            model=_required_text(model, "model"),
            source=_ESSAY_SOURCE,
            generated_at=_aware_utc(generated_at, "generated_at"),
        )
        self._replace_existing(record)
        return record

    def mark_failed(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> TransitEssayRecord:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        record = TransitEssayRecord(*key, status="failed")
        self._replace_existing(record)
        return record

    def delete_user(self, user_id: str) -> None:
        normalized = normalize_user_id(user_id)
        with self._lock:
            try:
                connection = self._connect()
                with connection:
                    connection.execute(
                        "DELETE FROM personal_transit_essays WHERE user_id = ?",
                        (normalized,),
                    )
            except sqlite3.Error as exc:
                raise TransitEssayStoreError(
                    "Transit essay storage is unavailable"
                ) from exc

    def delete_key(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> None:
        key = _essay_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            try:
                connection = self._connect()
                with connection:
                    connection.execute(
                        "DELETE FROM personal_transit_essays "
                        "WHERE user_id = ? AND cache_date = ? AND natal_fingerprint = ?",
                        key,
                    )
            except sqlite3.Error as exc:
                raise TransitEssayStoreError(
                    "Transit essay storage is unavailable"
                ) from exc

    def _replace_existing(self, record: TransitEssayRecord) -> None:
        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    cursor = connection.execute(
                        "UPDATE personal_transit_essays SET "
                        "status = ?, headline = ?, body = ?, watchpoints_json = ?, "
                        "epistemic = ?, model = ?, source = ?, generated_at = ? "
                        "WHERE user_id = ? AND cache_date = ? AND natal_fingerprint = ? "
                        "AND status = 'pending'",
                        (
                            record.status,
                            record.headline,
                            record.body,
                            json.dumps(list(record.watchpoints), ensure_ascii=False),
                            record.epistemic,
                            record.model,
                            record.source,
                            (
                                _utc_isoformat(record.generated_at)
                                if record.generated_at is not None
                                else None
                            ),
                            record.user_id,
                            record.cache_date,
                            record.natal_fingerprint,
                        ),
                    )
                if cursor.rowcount != 1:
                    raise TransitEssayStoreError(
                        "transit essay pending record disappeared"
                    )
            except sqlite3.Error as exc:
                raise TransitEssayStoreError(
                    "Transit essay storage is unavailable"
                ) from exc

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> TransitEssayRecord:
        try:
            raw_watchpoints = json.loads(str(row["watchpoints_json"]))
            if not isinstance(raw_watchpoints, list) or any(
                not isinstance(item, str) for item in raw_watchpoints
            ):
                raise ValueError("invalid watchpoints")
            raw_generated_at = row["generated_at"]
            generated_at = (
                None
                if raw_generated_at is None
                else datetime.fromisoformat(str(raw_generated_at).replace("Z", "+00:00"))
            )
            return TransitEssayRecord(
                user_id=str(row["user_id"]),
                cache_date=str(row["cache_date"]),
                natal_fingerprint=str(row["natal_fingerprint"]),
                status=str(row["status"]),
                headline=str(row["headline"]),
                body=str(row["body"]),
                watchpoints=tuple(raw_watchpoints),
                epistemic=str(row["epistemic"]),
                model=str(row["model"]),
                source=str(row["source"]),
                generated_at=generated_at,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise TransitEssayStoreError("Transit essay storage is invalid") from exc


@dataclass(frozen=True, slots=True)
class _TransitEssayJob:
    user_id: str
    cache_date: str
    natal_fingerprint: str
    facts: Mapping[str, Any]

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.user_id, self.cache_date, self.natal_fingerprint)


class _TransitEssayQueue:
    """Bounded daemon queue with queued-and-in-flight key de-duplication."""

    def __init__(
        self,
        worker: Callable[[_TransitEssayJob], None],
        *,
        maxsize: int = 256,
    ) -> None:
        if not callable(worker):
            raise TypeError("worker must be callable")
        if not isinstance(maxsize, int) or isinstance(maxsize, bool) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self._worker = worker
        self._jobs: queue.Queue[_TransitEssayJob] = queue.Queue(maxsize=maxsize)
        self._condition = Condition(RLock())
        self._pending: set[tuple[str, str, str]] = set()
        self._started = False
        self._closed = False
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("transit essay queue is closed")
            if self._started:
                return
            self._started = True
            self._thread = Thread(
                target=self._run,
                name="sidereal-transit-essay",
                daemon=True,
            )
            self._thread.start()

    def enqueue(self, job: _TransitEssayJob) -> bool:
        if not isinstance(job, _TransitEssayJob):
            raise TypeError("job must be a transit essay job")
        with self._condition:
            if not self._started or self._closed:
                raise TransitEssayError("transit essay queue is unavailable")
            if job.key in self._pending:
                return False
            self._pending.add(job.key)
            try:
                self._jobs.put_nowait(job)
            except queue.Full as exc:
                self._pending.remove(job.key)
                raise TransitEssayError("transit essay queue is full") from exc
            self._condition.notify_all()
            return True

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0.0:
            raise ValueError("timeout_seconds must be finite and non-negative")
        with self._condition:
            return self._condition.wait_for(
                lambda: not self._pending,
                timeout=float(timeout_seconds),
            )

    def close(self) -> None:
        with self._condition:
            self._closed = True
            while True:
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                self._jobs.task_done()
                self._pending.discard(job.key)
            thread = self._thread
            self._condition.notify_all()
        if thread is not None:
            thread.join(timeout=0.25)

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._closed and self._jobs.empty():
                    return
            try:
                job = self._jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._worker(job)
            except Exception as exc:  # worker failures must never reach HTTP
                _LOGGER.warning(
                    "Private transit essay worker failed (%s)",
                    type(exc).__name__,
                )
            finally:
                self._jobs.task_done()
                with self._condition:
                    self._pending.discard(job.key)
                    self._condition.notify_all()


TransitEssayFactsBuilder = Callable[..., dict[str, Any]]
TransitEssayClock = Callable[[], datetime]


class TransitEssayService:
    """Coordinate fingerprinted daily cache state and optional async authorship."""

    def __init__(
        self,
        store: TransitEssayStore,
        facts_builder: TransitEssayFactsBuilder,
        *,
        author: TransitEssayAuthor | None = None,
        clock: TransitEssayClock = lambda: datetime.now(UTC).replace(microsecond=0),
        queue_size: int = 256,
    ) -> None:
        if not callable(facts_builder):
            raise TypeError("facts_builder must be callable")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._store = store
        self._facts_builder = facts_builder
        self._author = author
        self._clock = clock
        self._facts_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._facts_condition = Condition(RLock())
        self._facts_pending: set[tuple[str, str, str]] = set()
        self._facts_generation: dict[str, int] = {}
        self._queue = (
            None
            if author is None
            else _TransitEssayQueue(self._run_job, maxsize=queue_size)
        )

    @property
    def available(self) -> bool:
        return self._author is not None

    def start(self) -> None:
        if self._queue is not None:
            self._queue.start()

    def close(self) -> None:
        if self._queue is not None:
            self._queue.close()
        closer = getattr(self._store, "close", None)
        if callable(closer):
            closer()

    def ensure(self, record: NatalRecord) -> dict[str, Any]:
        instant, cache_date, fingerprint = self._context(record)
        if self._queue is None:
            return _transient_status("unavailable", cache_date)
        current = self._store.get(record.user_id, cache_date, fingerprint)
        # Ready is day-stable. Failed is retryable so a bad model response does not
        # brick the note until civil midnight.
        if current is not None and current.status == "ready":
            return current.to_api_dict()
        if current is not None and current.status == "failed":
            # Retry failed day without wiping other cached notes.
            clearer = getattr(self._store, "delete_key", None)
            if callable(clearer):
                clearer(record.user_id, cache_date, fingerprint)
            else:
                self._store.delete_user(record.user_id)

        facts = self._facts_for_context(
            record,
            instant=instant,
            cache_date=cache_date,
            fingerprint=fingerprint,
        )
        pending = self._store.ensure_pending(
            record.user_id,
            cache_date,
            fingerprint,
        )
        if pending.status in {"ready", "failed"}:
            return pending.to_api_dict()
        job = _TransitEssayJob(
            user_id=record.user_id,
            cache_date=cache_date,
            natal_fingerprint=fingerprint,
            facts=facts,
        )
        try:
            self._queue.enqueue(job)
        except TransitEssayError:
            failed = self._store.mark_failed(
                record.user_id,
                cache_date,
                fingerprint,
            )
            return failed.to_api_dict()
        return pending.to_api_dict()

    def get(self, record: NatalRecord) -> dict[str, Any]:
        _instant, cache_date, fingerprint = self._context(record)
        if self._queue is None:
            return _transient_status("unavailable", cache_date)
        current = self._store.get(record.user_id, cache_date, fingerprint)
        if current is not None and current.status in {"ready", "failed"}:
            return current.to_api_dict()
        if current is not None:
            return current.to_api_dict()
        return _transient_status("none", cache_date)

    def brief(self, record: NatalRecord) -> dict[str, Any]:
        """Build a facts-only daily brief and append only this key's ready essay."""

        instant, cache_date, fingerprint = self._context(record)
        try:
            facts = self._facts_for_context(
                record,
                instant=instant,
                cache_date=cache_date,
                fingerprint=fingerprint,
            )
            try:
                current = self._store.get(record.user_id, cache_date, fingerprint)
            except TransitEssayStoreError:
                current = None
            essay = current if current is not None and current.status == "ready" else None
            text = format_sky_brief_text(facts, essay=essay)
        except (
            EphemerisError,
            InterpretationStoreError,
            OSError,
            TypeError,
            ValueError,
        ):
            return {
                "status": "failed",
                "cache_date": cache_date,
                "timezone": record.tz,
                "text": "",
                "has_essay": False,
                "epistemic": SKY_BRIEF_EPISTEMIC,
            }
        return {
            "status": "ready",
            "cache_date": cache_date,
            "timezone": record.tz,
            "text": text,
            "has_essay": essay is not None,
            "epistemic": SKY_BRIEF_EPISTEMIC,
        }

    def invalidate_user(self, user_id: str) -> None:
        normalized = normalize_user_id(user_id)
        try:
            self._store.delete_user(normalized)
        finally:
            with self._facts_condition:
                self._facts_generation[normalized] = (
                    self._facts_generation.get(normalized, 0) + 1
                )
                for key in tuple(self._facts_cache):
                    if key[0] == normalized:
                        self._facts_cache.pop(key, None)
                self._facts_condition.notify_all()

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        return (
            True
            if self._queue is None
            else self._queue.wait_until_idle(timeout_seconds)
        )

    def _context(self, record: NatalRecord) -> tuple[datetime, str, str]:
        if not isinstance(record, NatalRecord):
            raise TypeError("record must be a NatalRecord")
        instant = _aware_utc(self._clock(), "clock result")
        return (
            instant,
            transit_essay_cache_date(record, instant),
            natal_fingerprint(record),
        )

    def _facts_for_context(
        self,
        record: NatalRecord,
        *,
        instant: datetime,
        cache_date: str,
        fingerprint: str,
    ) -> dict[str, Any]:
        key = _essay_key(record.user_id, cache_date, fingerprint)
        with self._facts_condition:
            while True:
                cached = self._facts_cache.get(key)
                if cached is not None:
                    return deepcopy(cached)
                if key not in self._facts_pending:
                    self._facts_pending.add(key)
                    generation = self._facts_generation.get(record.user_id, 0)
                    break
                self._facts_condition.wait()

        try:
            facts = self._facts_builder(record, when=instant)
            if not isinstance(facts, dict):
                raise TypeError("transit essay facts builder must return a dict")
            if facts.get("cache_date") != cache_date:
                raise TransitEssayValidationError(
                    "transit essay facts cache_date disagrees with the user civil day"
                )
            snapshot = deepcopy(facts)
        except Exception:
            with self._facts_condition:
                self._facts_pending.discard(key)
                self._facts_condition.notify_all()
            raise

        with self._facts_condition:
            if generation == self._facts_generation.get(record.user_id, 0):
                existing = self._facts_cache.setdefault(key, snapshot)
                while len(self._facts_cache) > 2_048:
                    self._facts_cache.pop(next(iter(self._facts_cache)))
            else:
                existing = snapshot
            self._facts_pending.discard(key)
            self._facts_condition.notify_all()
            return deepcopy(existing)

    def _run_job(self, job: _TransitEssayJob) -> None:
        assert self._author is not None
        try:
            content = self._author.generate(job.facts)
            if not isinstance(content, GeneratedTransitEssay):
                raise TransitEssayValidationError(
                    "transit essay author returned an invalid result type"
                )
            content = validate_transit_essay_content(content.to_dict(), job.facts)
            self._store.mark_ready(
                job.user_id,
                job.cache_date,
                job.natal_fingerprint,
                content,
                model=self._author.model,
                generated_at=_aware_utc(self._clock(), "clock result"),
            )
        except Exception as exc:
            try:
                self._store.mark_failed(
                    job.user_id,
                    job.cache_date,
                    job.natal_fingerprint,
                )
            except Exception:
                pass
            _LOGGER.warning(
                "Private transit essay generation failed (%s)",
                type(exc).__name__,
            )


def transit_essay_service_from_env(
    db_path: Path | str,
    facts_builder: TransitEssayFactsBuilder,
) -> TransitEssayService:
    """Build persistent-if-available private essay service from server config."""

    path = Path(db_path).expanduser()
    store: TransitEssayStore = (
        SQLiteTransitEssayStore(path)
        if path.is_file()
        else MemoryTransitEssayStore()
    )
    raw_key = os.environ.get("DEEPSEEK_API_KEY")
    author = (
        None
        if raw_key is None or not raw_key.strip()
        else DeepSeekTransitEssayAuthor.from_env()
    )
    return TransitEssayService(store, facts_builder, author=author)


def _transient_status(status: str, cache_date: str) -> dict[str, Any]:
    if status not in {"none", "unavailable"}:
        raise ValueError("invalid transient transit essay status")
    _canonical_cache_date(cache_date)
    return {
        "schema_version": TRANSIT_ESSAY_SCHEMA_VERSION,
        "type": TRANSIT_ESSAY_TYPE,
        "status": status,
        "cache_date": cache_date,
    }


def _essay_key(
    user_id: str,
    cache_date: str,
    natal_fingerprint_value: str,
) -> tuple[str, str, str]:
    normalized_user = normalize_user_id(user_id)
    if user_id != normalized_user:
        raise ValueError("user_id must already be normalized")
    canonical_date = _canonical_cache_date(cache_date)
    if (
        not isinstance(natal_fingerprint_value, str)
        or _FINGERPRINT_RE.fullmatch(natal_fingerprint_value) is None
    ):
        raise ValueError("natal_fingerprint must be a lowercase SHA-256 digest")
    return normalized_user, canonical_date, natal_fingerprint_value


def _canonical_cache_date(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("cache_date must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("cache_date must be an ISO date") from exc
    canonical = parsed.isoformat()
    if value != canonical:
        raise ValueError("cache_date must be a canonical ISO date")
    return canonical


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _utc_isoformat(value: datetime) -> str:
    return _aware_utc(value, "timestamp").isoformat()


__all__ = [
    "DeepSeekTransitEssayAuthor",
    "GeneratedTransitEssay",
    "MemoryTransitEssayStore",
    "SKY_BRIEF_EPISTEMIC",
    "SQLiteTransitEssayStore",
    "TRANSIT_ESSAY_EPISTEMIC",
    "TRANSIT_ESSAY_FACTS_TYPE",
    "TRANSIT_ESSAY_MAX_ASPECTS",
    "TRANSIT_ESSAY_SCHEMA_VERSION",
    "TRANSIT_ESSAY_SYSTEM_PROMPT",
    "TRANSIT_ESSAY_TYPE",
    "TransitEssayAuthor",
    "TransitEssayError",
    "TransitEssayRecord",
    "TransitEssayService",
    "TransitEssayStore",
    "TransitEssayStoreError",
    "TransitEssayValidationError",
    "build_transit_essay_facts",
    "format_sky_brief_text",
    "natal_fingerprint",
    "transit_essay_cache_date",
    "transit_essay_service_from_env",
    "validate_transit_essay_content",
]
