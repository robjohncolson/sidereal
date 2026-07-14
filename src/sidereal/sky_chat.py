"""Private, focus-scoped Sky Temple dialogue grounded in transit geometry."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
import unicodedata
from uuid import uuid4
from zoneinfo import ZoneInfo

from .aspects import TRANSIT_ASPECT_BODY_IDS
from .auth import normalize_user_id
from .config import ASPECT_POINT_IDS, BODY_IDS
from .interpret.ai_seed import (
    BANNED_GENERATED_FRAGMENTS,
    DeepSeekConfig,
    DeepSeekRequestError,
    DeepSeekTransport,
    UrllibDeepSeekTransport,
)
from .interpret.schema import ASPECT_TYPES, SIGNS
from .natal import NatalRecord
from .timebase import parse_timezone, resolve_moment
from .transit_essay import (
    InterpretationLookup,
    build_transit_essay_facts,
    natal_fingerprint,
    transit_essay_cache_date,
)
from .types import MomentInput


SKY_CHAT_SCHEMA_VERSION = 1
SKY_CHAT_TYPE = "sky_chat"
SKY_CHAT_FACTS_TYPE = "sky_chat_facts"
SKY_CHAT_EPISTEMIC = (
    "Symbolic study notes, not predictions. "
    "Not medical, legal, or financial advice."
)
SKY_CHAT_MAX_MESSAGE_CHARS = 800
SKY_CHAT_MAX_REPLIES_PER_DAY = 10
SKY_CHAT_MAX_HISTORY_TURNS = 8
SKY_CHAT_MAX_REPLY_WORDS = 600
SKY_CHAT_FULL_ASPECT_CAP = len(TRANSIT_ASPECT_BODY_IDS) * len(ASPECT_POINT_IDS)
SKY_CHAT_SYSTEM_PROMPT = """You answer one private Sky Temple study question for Sidereal.
Use the Midpoint 13-sign symbolic framework and treat Ophiuchus as a first-class sign.
Use only the supplied fact packet and prior turns. Never invent or imply an aspect, placement, orb, or motion state absent from the facts. If the facts are insufficient, state only what is known and stop.
When stating geometry, use only explicit forms such as "Transit Mars square natal Moon has an orb of 0.5 degrees and is applying" or "Transit Mars is in Leo" so every claim can be checked against the packet; do not paraphrase geometry.
Write tentative symbolic study language, not personality verdicts, event forecasts, fate guarantees, or medical, legal, financial, crisis, or treatment guidance.
Reply in plain-language paragraphs of roughly 80-180 words.
Return only one JSON object with exactly one field: reply (string).
Do not use HTML, Markdown fences, or commentary outside the JSON object."""

_FOCUS_KINDS = frozenset(("body", "sign", "natal", "aspect", "sky"))
_FOCUS_FIELDS = frozenset(
    ("kind", "body", "sign", "natal_point", "aspect_id", "label")
)
_NATAL_FOCUS_IDS = frozenset((*BODY_IDS, "asc", "mc"))
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
_CHAT_BANNED_FRAGMENTS = frozenset(
    (
        *BANNED_GENERATED_FRAGMENTS,
        "will happen",
        "will bring",
        "guarantee",
        "medical",
        "financial",
        "legal",
        "fated",
        "fate",
        "destined",
        "diagnosis",
        "treatment",
        "prescription",
    )
)
_BODY_REFERENCE_PATTERN = (
    r"sun|moon|mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto|"
    r"north[ _-]?node|south[ _-]?node|ascendant|midheaven|asc|mc"
)
_ASPECT_REFERENCE_PATTERN = (
    r"conjunct(?:ion|s)?|oppos(?:ition|ite|es|ed)|trin(?:e|es)|"
    r"squar(?:e|es|ed)|sextil(?:e|es)"
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
_BETWEEN_ASPECT_RE = re.compile(
    rf"\b(?P<aspect>{_ASPECT_REFERENCE_PATTERN})(?:\s+aspect)?\s+between\s+"
    rf"(?:transit(?:ing)?\s+)?(?P<transit>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:and|with)\s+(?:your\s+|the\s+)?(?:natal\s+)?"
    rf"(?P<natal>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_COPULAR_ASPECT_RE = re.compile(
    rf"\b(?:transit(?:ing)?\s+)?(?P<transit>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:and|with)\s+(?:your\s+|the\s+)?(?:natal\s+)?"
    rf"(?P<natal>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:are|is|remain|feel|sit)\s+(?:in\s+an?\s+)?"
    rf"(?P<aspect>{_ASPECT_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_FROM_ASPECT_RE = re.compile(
    rf"\b(?:your\s+|the\s+)?(?:natal\s+)?"
    rf"(?P<natal>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:receives?|holds?|has|makes?)\s+(?:an?\s+)?"
    rf"(?P<aspect>{_ASPECT_REFERENCE_PATTERN})\s+"
    rf"(?:from|with)\s+(?:transit(?:ing)?\s+)?"
    rf"(?P<transit>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_LINK_ASPECT_RE = re.compile(
    rf"\b(?P<aspect>{_ASPECT_REFERENCE_PATTERN})(?:\s+aspect)?\s+"
    rf"(?:links?|connects?|joins?)\s+"
    rf"(?:transit(?:ing)?\s+)?(?P<transit>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:to|with|and)\s+(?:your\s+|the\s+)?(?:natal\s+)?"
    rf"(?P<natal>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_PAIR_CONNECTION_ASPECT_RE = re.compile(
    rf"\b(?:transit(?:ing)?\s+)?(?P<transit>{_BODY_REFERENCE_PATTERN})\s*"
    rf"(?:[-–—/]\s*|(?:and|with)\s+)"
    rf"(?:your\s+|the\s+)?(?:natal\s+)?(?P<natal>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:connection|contact|relationship)\s+"
    rf"(?:forms?|makes?|is)\s+(?:an?\s+)?"
    rf"(?P<aspect>{_ASPECT_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_ASPECT_LEXEME_RE = re.compile(
    rf"\b(?P<aspect>{_ASPECT_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_EXPLICIT_TRANSIT_RE = re.compile(
    rf"\btransit(?:ing)?\s+(?P<body>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_EXPLICIT_NATAL_RE = re.compile(
    rf"\bnatal\s+(?P<body>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_UNLABELED_PAIR_ASPECT_RE = re.compile(
    rf"\b(?P<transit>{_BODY_REFERENCE_PATTERN})\s*"
    rf"(?:[-–—/]\s*|(?:and|with)\s+)"
    rf"(?P<natal>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?P<aspect>{_ASPECT_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_SIGN_REFERENCE_PATTERN = (
    r"aries|taurus|gemini|cancer|leo|virgo|libra|scorpio|ophiuchus|"
    r"sagittarius|capricorn|aquarius|pisces"
)
_BODY_IN_SIGN_RE = re.compile(
    rf"\b(?:(?P<role>transit(?:ing)?|natal)\s+)?"
    rf"(?P<body>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:(?:is|is\s+located|sits?|stands?|lies?|rests?|resides?|dwells?|moves?|travels?|can\s+be\s+found)\s+)?"
    rf"(?:currently\s+)?"
    rf"(?:in|through)\s+(?P<sign>{_SIGN_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_SIGN_CONTAINS_BODY_RE = re.compile(
    rf"\b(?P<sign>{_SIGN_REFERENCE_PATTERN})\s+"
    rf"(?:contains?|holds?|hosts?)\s+"
    rf"(?:(?P<role>transit(?:ing)?|natal)\s+)?"
    rf"(?P<body>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_SIGN_OCCUPIED_BY_BODY_RE = re.compile(
    rf"\b(?P<sign>{_SIGN_REFERENCE_PATTERN})\s+is\s+occupied\s+by\s+"
    rf"(?:(?P<role>transit(?:ing)?|natal)\s+)?"
    rf"(?P<body>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_BODY_ENTERS_SIGN_RE = re.compile(
    rf"\b(?:(?P<role>transit(?:ing)?|natal)\s+)?"
    rf"(?P<body>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:currently\s+)?(?:enters?|entered|entering|moves?\s+into)\s+"
    rf"(?P<sign>{_SIGN_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_BODY_OCCUPIES_SIGN_RE = re.compile(
    rf"\b(?:(?P<role>transit(?:ing)?|natal)\s+)?"
    rf"(?P<body>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:currently\s+)?occup(?:y|ies)\s+"
    rf"(?P<sign>{_SIGN_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_BODY_AT_SIGN_DEGREE_RE = re.compile(
    rf"\b(?:(?P<role>transit(?:ing)?|natal)\s+)?"
    rf"(?P<body>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:(?:is|sits?|stands?|lies?|rests?)\s+)?at\s+"
    rf"(?P<degree>\d+(?:\.\d+)?)\s*(?:°|degrees?)\s+"
    rf"(?:of\s+|in\s+)?(?P<sign>{_SIGN_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_BODY_MOTION_RE = re.compile(
    rf"\b(?:(?P<role>transit(?:ing)?|natal)\s+)?"
    rf"(?P<body>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:(?:is\s+stationing|is|appears?|moves?|remains?|stations?|stationed|stationing|turns?|turned|has\s+turned)\s+)?"
    rf"(?P<motion>not\s+retrograde|retrograde|retro|direct|prograde|"
    rf"moving\s+backwards?|moving\s+forwards?|backwards?|forwards?)\b",
    flags=re.IGNORECASE,
)
_ORB_CLAIM_RE = re.compile(
    r"\borb\s*(?:is|of|at|:)?\s*(?P<orb>\d+(?:\.\d+)?)\s*"
    r"(?:°|degrees?\b)",
    flags=re.IGNORECASE,
)
_VALUE_ORB_CLAIM_RE = re.compile(
    r"\b(?P<orb>\d+(?:\.\d+)?)\s*(?:°|degrees?)\s+orb\b",
    flags=re.IGNORECASE,
)
_FROM_EXACT_CLAIM_RE = re.compile(
    r"\b(?P<orb>\d+(?:\.\d+)?)\s*(?:°|degrees?)\s+"
    r"(?:away\s+)?from\s+(?:being\s+)?exact\b",
    flags=re.IGNORECASE,
)
_WIDE_ORB_CLAIM_RE = re.compile(
    r"\b(?P<orb>\d+(?:\.\d+)?)\s*(?:°|degrees?)\s+wide\b",
    flags=re.IGNORECASE,
)
_EXACT_CLAIM_RE = re.compile(
    r"\b(?:is|was|appears?|becomes?|became|remains?)\s+exact\b",
    flags=re.IGNORECASE,
)
_ANGLE_CLAIM_RE = re.compile(
    rf"\b(?:transit(?:ing)?\s+)?(?P<transit>{_BODY_REFERENCE_PATTERN})\s+"
    rf"(?:forms?|makes?|has)\s+(?:an?\s+)?"
    rf"(?P<separation>\d+(?:\.\d+)?)\s*(?:(?:-\s*)?degrees?|°)\s+"
    rf"(?:angle|separation)\s+(?:to|with|from)\s+"
    rf"(?:your\s+|the\s+)?(?:natal\s+)?(?P<natal>{_BODY_REFERENCE_PATTERN})\b",
    flags=re.IGNORECASE,
)
_PHASE_CLAIM_RE = re.compile(
    r"\b(?:(?:is|was|appears?|remains?)\s+|(?:°|degrees?)\s+and\s+)"
    r"(?P<phase>not\s+applying|applying|separating|tightening|widening)\b",
    flags=re.IGNORECASE,
)
_CHAT_CLAUSE_SPLIT_RE = re.compile(r"(?<=\.)(?!\d)|(?<=[!?;])|\n+")
_LOGGER = logging.getLogger(__name__)


class SkyChatError(RuntimeError):
    """Base error for private Sky Temple dialogue."""


class SkyChatValidationError(SkyChatError, ValueError):
    """A request, fact packet, or generated reply failed validation."""


class SkyChatStoreError(SkyChatError):
    """Private Sky Chat persistence could not complete an operation."""


class SkyChatPendingError(SkyChatError):
    """A thread already has one assistant turn in progress."""


class SkyChatRateLimitError(SkyChatError):
    """A thread already has the maximum successful replies for its civil day."""


@dataclass(frozen=True, slots=True)
class SkyChatFocus:
    """Canonical selectors retained from an untrusted client focus object."""

    kind: str
    body: str = ""
    sign: str = ""
    natal_point: str = ""
    aspect_id: str = ""

    def __post_init__(self) -> None:
        if self.kind not in _FOCUS_KINDS:
            raise ValueError("invalid Sky Chat focus kind")
        if self.kind == "body" and self.body not in BODY_IDS:
            raise ValueError("invalid Sky Chat body focus")
        if self.kind == "sign" and self.sign not in SIGNS:
            raise ValueError("invalid Sky Chat sign focus")
        if self.kind == "natal" and self.natal_point not in _NATAL_FOCUS_IDS:
            raise ValueError("invalid Sky Chat natal focus")
        if self.kind == "aspect" and (
            self.body not in TRANSIT_ASPECT_BODY_IDS
            or self.natal_point not in ASPECT_POINT_IDS
            or self.aspect_id not in ASPECT_TYPES
        ):
            raise ValueError("invalid Sky Chat aspect focus")

    def to_dict(self) -> dict[str, str]:
        result = {"kind": self.kind}
        if self.kind in {"body", "aspect"}:
            result["body"] = self.body
        if self.kind == "sign":
            result["sign"] = self.sign
        if self.kind in {"natal", "aspect"}:
            result["natal_point"] = self.natal_point
        if self.kind == "aspect":
            result["aspect_id"] = self.aspect_id
        return result


def normalize_sky_chat_focus(value: Mapping[str, Any]) -> SkyChatFocus:
    """Validate focus selectors and discard display-only client labels."""

    if not isinstance(value, Mapping):
        raise SkyChatValidationError("focus must be an object")
    extras = sorted(set(value) - _FOCUS_FIELDS)
    if extras:
        raise SkyChatValidationError(
            f"unsupported focus field(s): {', '.join(str(item) for item in extras)}"
        )
    label = value.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > 240):
        raise SkyChatValidationError("focus.label must be a string of at most 240 characters")
    kind = _selector(value.get("kind"), "focus.kind")
    if kind not in _FOCUS_KINDS:
        raise SkyChatValidationError(
            "focus.kind must be body, sign, natal, aspect, or sky"
        )
    if kind == "body":
        body = _selector(value.get("body"), "focus.body")
        if body not in BODY_IDS:
            raise SkyChatValidationError("focus.body is not a supported transit body")
        return SkyChatFocus(kind=kind, body=body)
    if kind == "sign":
        sign = _selector(value.get("sign"), "focus.sign")
        if sign not in SIGNS:
            raise SkyChatValidationError("focus.sign is not a Midpoint sign")
        return SkyChatFocus(kind=kind, sign=sign)
    if kind == "natal":
        natal_point = _selector(value.get("natal_point"), "focus.natal_point")
        if natal_point not in _NATAL_FOCUS_IDS:
            raise SkyChatValidationError("focus.natal_point is not supported")
        return SkyChatFocus(kind=kind, natal_point=natal_point)
    if kind == "aspect":
        body = _selector(value.get("body"), "focus.body")
        natal_point = _selector(value.get("natal_point"), "focus.natal_point")
        aspect_id = _selector(value.get("aspect_id"), "focus.aspect_id")
        if body not in TRANSIT_ASPECT_BODY_IDS:
            raise SkyChatValidationError("focus.body cannot form a supported transit aspect")
        if natal_point not in ASPECT_POINT_IDS:
            raise SkyChatValidationError("focus.natal_point cannot form a supported aspect")
        if aspect_id not in ASPECT_TYPES:
            raise SkyChatValidationError("focus.aspect_id is not a major aspect")
        return SkyChatFocus(
            kind=kind,
            body=body,
            natal_point=natal_point,
            aspect_id=aspect_id,
        )
    return SkyChatFocus(kind="sky")


def validate_sky_chat_message(value: Any) -> str:
    """Normalize one bounded question and reject control-character spam."""

    if not isinstance(value, str):
        raise SkyChatValidationError("message must be a string")
    if len(value) > SKY_CHAT_MAX_MESSAGE_CHARS:
        raise SkyChatValidationError(
            f"message must contain at most {SKY_CHAT_MAX_MESSAGE_CHARS} characters"
        )
    normalized = value.strip()
    if not normalized:
        raise SkyChatValidationError("message must be non-empty")
    if any(
        unicodedata.category(character).startswith("C")
        for character in normalized
        if character not in "\n\t"
    ):
        raise SkyChatValidationError("message contains unsupported control characters")
    return normalized


def build_sky_chat_facts(
    record: NatalRecord,
    focus: Mapping[str, Any] | SkyChatFocus,
    *,
    when: datetime | None = None,
    store: InterpretationLookup | None = None,
    boundary_path: Path | str | None = None,
    ephe_path: Path | str | None = None,
    require_swiss_ephemeris: bool = False,
) -> dict[str, Any]:
    """Build a private, focus-capped fact packet from server ephemeris geometry."""

    if not isinstance(record, NatalRecord):
        raise TypeError("record must be a NatalRecord")
    selected = focus if isinstance(focus, SkyChatFocus) else normalize_sky_chat_focus(focus)
    instant = _aware_utc(
        when or datetime.now(UTC).replace(microsecond=0),
        "when",
    )
    base = build_transit_essay_facts(
        record,
        when=instant,
        store=store,
        boundary_path=boundary_path,
        ephe_path=ephe_path,
        require_swiss_ephemeris=require_swiss_ephemeris,
        max_aspects=SKY_CHAT_FULL_ASPECT_CAP,
    )
    natal = tuple(_placement_fact(item) for item in _mapping_items(base, "natal", "placements"))
    movers = tuple(_placement_fact(item) for item in _mapping_items(base, "sky", "movers"))
    deltas = tuple(_delta_fact(item) for item in _list_items(base.get("same_body_delta")))
    aspects = tuple(_chat_aspect_fact(item) for item in _list_items(base.get("aspects")))
    natal_by_id = {str(item["body"]): item for item in natal}
    mover_by_id = {str(item["body"]): item for item in movers}
    delta_by_id = {str(item["body"]): item for item in deltas}

    result: dict[str, Any] = {
        "schema_version": SKY_CHAT_SCHEMA_VERSION,
        "type": SKY_CHAT_FACTS_TYPE,
        "cache_date": str(base["cache_date"]),
        "timezone": str(base["timezone"]),
        "epoch_utc": str(base["epoch_utc"]),
        "focus": selected.to_dict(),
        "natal_placements_short": [],
        "movers_short": [],
        "aspects": [],
    }

    if selected.kind == "body":
        placement = mover_by_id.get(selected.body)
        if placement is None:
            raise SkyChatValidationError("focused transit body is unavailable")
        related = tuple(
            item for item in aspects if item["transit_body"] == selected.body
        )[:6]
        natal_ids = (selected.body, *(str(item["natal_point"]) for item in related))
        result.update(
            movers_short=[dict(placement)],
            natal_placements_short=_placements_for_ids(natal_by_id, natal_ids, limit=8),
            transit_body=dict(placement),
            same_body_delta=(
                dict(delta_by_id[selected.body])
                if selected.body in delta_by_id
                else None
            ),
            aspects=[dict(item) for item in related],
        )
        return result

    if selected.kind == "natal":
        placement = natal_by_id.get(selected.natal_point)
        if placement is None:
            raise SkyChatValidationError(
                "focused natal point is unavailable for this saved chart"
            )
        related = tuple(
            item for item in aspects if item["natal_point"] == selected.natal_point
        )[:6]
        mover_ids = tuple(str(item["transit_body"]) for item in related)
        result.update(
            movers_short=_placements_for_ids(mover_by_id, mover_ids, limit=6),
            natal_placements_short=[dict(placement)],
            natal_point=dict(placement),
            aspects=[dict(item) for item in related],
        )
        return result

    if selected.kind == "aspect":
        contact = next(
            (
                item
                for item in aspects
                if item["transit_body"] == selected.body
                and item["natal_point"] == selected.natal_point
                and item["aspect_id"] == selected.aspect_id
            ),
            None,
        )
        if contact is None:
            raise SkyChatValidationError(
                "focused aspect is absent from the recomputed ephemeris geometry"
            )
        transit_placement = mover_by_id.get(selected.body)
        natal_placement = natal_by_id.get(selected.natal_point)
        if transit_placement is None or natal_placement is None:
            raise SkyChatValidationError("focused aspect placements are unavailable")
        other = tuple(item for item in aspects if item is not contact)
        adjacent = tuple(
            item
            for item in other
            if item["transit_body"] == selected.body
            or item["natal_point"] == selected.natal_point
        )
        neighbors = list(adjacent[:4])
        for item in other:
            if len(neighbors) >= 4:
                break
            if item not in neighbors:
                neighbors.append(item)
        scoped = (contact, *neighbors)
        mover_ids = (selected.body, *(str(item["transit_body"]) for item in neighbors))
        natal_ids = (
            selected.natal_point,
            *(str(item["natal_point"]) for item in neighbors),
        )
        result.update(
            movers_short=_placements_for_ids(mover_by_id, mover_ids, limit=8),
            natal_placements_short=_placements_for_ids(natal_by_id, natal_ids, limit=8),
            transit_placement=dict(transit_placement),
            natal_placement=dict(natal_placement),
            focus_aspect=dict(contact),
            neighbor_aspects=[dict(item) for item in neighbors],
            aspects=[dict(item) for item in scoped],
        )
        return result

    if selected.kind == "sign":
        movers_in_sign = [dict(item) for item in movers if item.get("sign") == selected.sign]
        natal_in_sign = [dict(item) for item in natal if item.get("sign") == selected.sign]
        result.update(
            movers_short=movers_in_sign,
            natal_placements_short=natal_in_sign,
            movers_in_sign=movers_in_sign,
            natal_in_sign=natal_in_sign,
        )
        summary = _ready_sign_summary(store, selected.sign)
        if summary:
            result["sign_seed_summary"] = summary
        return result

    top = aspects[:8]
    mover_ids = (
        "sun",
        "moon",
        *(str(item["transit_body"]) for item in top),
    )
    natal_ids = (
        "sun",
        "moon",
        *(str(item["natal_point"]) for item in top),
    )
    transit_luminaries = _placements_for_ids(mover_by_id, ("sun", "moon"), limit=2)
    natal_luminaries = _placements_for_ids(natal_by_id, ("sun", "moon"), limit=2)
    result.update(
        movers_short=_placements_for_ids(mover_by_id, mover_ids, limit=8),
        natal_placements_short=_placements_for_ids(natal_by_id, natal_ids, limit=8),
        luminaries={
            "transit": transit_luminaries,
            "natal": natal_luminaries,
        },
        aspects=[dict(item) for item in top],
    )
    return result


@dataclass(frozen=True, slots=True)
class GeneratedSkyChatReply:
    """One provider reply after deterministic schema and safety validation."""

    reply: str

    def to_dict(self) -> dict[str, str]:
        return {"reply": self.reply}


def validate_sky_chat_reply(
    payload: Mapping[str, Any],
    facts: Mapping[str, Any],
) -> GeneratedSkyChatReply:
    """Reject malformed, unsafe, overlong, or geometry-inventing model text."""

    if not isinstance(payload, Mapping):
        raise SkyChatValidationError("Sky Chat reply must be a JSON object")
    if set(payload) != {"reply"}:
        raise SkyChatValidationError("Sky Chat reply must contain exactly reply")
    reply = payload.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise SkyChatValidationError("Sky Chat reply must be a non-empty string")
    normalized = reply.strip()
    if len(normalized) > 4_000:
        raise SkyChatValidationError("Sky Chat reply is too long")
    if len(re.findall(r"\b[\w’'-]+\b", normalized, flags=re.UNICODE)) > SKY_CHAT_MAX_REPLY_WORDS:
        raise SkyChatValidationError("Sky Chat reply exceeds the word limit")
    if "<" in normalized or ">" in normalized or "```" in normalized:
        raise SkyChatValidationError("Sky Chat reply must be plain text")
    folded = re.sub(r"\s+", " ", normalized.casefold())
    banned = next(
        (fragment for fragment in _CHAT_BANNED_FRAGMENTS if fragment in folded),
        None,
    )
    if banned is not None:
        raise SkyChatValidationError(
            f"Sky Chat reply contains banned fragment {banned!r}"
        )
    _validate_reply_aspects(normalized, facts)
    _validate_reply_placements_and_motion(normalized, facts)
    return GeneratedSkyChatReply(reply=normalized)


class SkyChatAuthor(Protocol):
    @property
    def model(self) -> str:
        ...

    def generate(
        self,
        facts: Mapping[str, Any],
        history: Sequence[Mapping[str, str]],
        message: str,
    ) -> GeneratedSkyChatReply:
        ...


class DeepSeekSkyChatAuthor:
    """Strict non-streaming DeepSeek author for one grounded chat turn."""

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
    def from_env(cls) -> DeepSeekSkyChatAuthor:
        return cls(DeepSeekConfig.from_env())

    def generate(
        self,
        facts: Mapping[str, Any],
        history: Sequence[Mapping[str, str]],
        message: str,
    ) -> GeneratedSkyChatReply:
        if not isinstance(facts, Mapping):
            raise TypeError("facts must be a mapping")
        question = validate_sky_chat_message(message)
        safe_history = _validated_history(history)[-SKY_CHAT_MAX_HISTORY_TURNS:]
        user_content = json.dumps(
            {
                "facts": dict(facts),
                "history": safe_history,
                "message": question,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": SKY_CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0.4,
            "max_tokens": 900,
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
            raise DeepSeekRequestError("DeepSeek returned no Sky Chat choice")
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise DeepSeekRequestError("DeepSeek returned an invalid Sky Chat choice")
        if choice.get("finish_reason") not in {None, "stop", "length"}:
            raise DeepSeekRequestError("DeepSeek Sky Chat did not finish cleanly")
        provider_message = choice.get("message")
        content = (
            provider_message.get("content")
            if isinstance(provider_message, Mapping)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekRequestError("DeepSeek returned an empty Sky Chat reply")
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(
                r"^```(?:json)?\s*",
                "",
                cleaned,
                count=1,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r"\s*```$", "", cleaned, count=1)
        try:
            decoded = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise DeepSeekRequestError("DeepSeek Sky Chat was not valid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise DeepSeekRequestError("DeepSeek Sky Chat JSON must be an object")
        validated = validate_sky_chat_reply(decoded, facts)
        if self._config.api_key in validated.reply:
            raise DeepSeekRequestError("DeepSeek Sky Chat reply failed credential safety")
        return validated


@dataclass(frozen=True, slots=True)
class SkyChatTurn:
    """One persisted user question or assistant outcome."""

    turn_id: str
    role: str
    text: str
    at: datetime
    focus: SkyChatFocus | None = None
    status: str = ""
    epoch: datetime | None = None

    def __post_init__(self) -> None:
        _canonical_token(self.turn_id, "turn_id")
        if self.role not in {"user", "assistant"}:
            raise ValueError("turn role must be user or assistant")
        if not isinstance(self.text, str):
            raise ValueError("turn text must be a string")
        _aware_utc(self.at, "turn at")
        if self.role == "user":
            if self.focus is None or self.status or self.epoch is None:
                raise ValueError("user turns require focus and epoch only")
            validate_sky_chat_message(self.text)
            _aware_utc(self.epoch, "turn epoch")
        else:
            if self.focus is not None or self.epoch is not None:
                raise ValueError("assistant turns cannot carry focus or epoch")
            if self.status not in {"ready", "failed"}:
                raise ValueError("assistant turn status must be ready or failed")
            if self.status == "ready" and not self.text:
                raise ValueError("ready assistant turns require text")
            if self.status == "failed" and self.text:
                raise ValueError("failed assistant turns cannot retain provider text")

    def to_api_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role": self.role,
            "text": self.text,
            "at": _utc_isoformat(self.at),
        }
        if self.role == "user":
            assert self.focus is not None
            result["focus"] = self.focus.to_dict()
        else:
            result["status"] = self.status
        return result

    def to_storage_dict(self) -> dict[str, Any]:
        result = self.to_api_dict()
        result["turn_id"] = self.turn_id
        if self.epoch is not None:
            result["epoch"] = _utc_isoformat(self.epoch)
        return result

    @classmethod
    def from_storage_dict(cls, value: Mapping[str, Any]) -> SkyChatTurn:
        if not isinstance(value, Mapping):
            raise ValueError("stored turn must be an object")
        role = str(value.get("role") or "")
        raw_at = value.get("at")
        if not isinstance(raw_at, str):
            raise ValueError("stored turn at must be an ISO timestamp")
        at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
        if role == "user":
            raw_epoch = value.get("epoch")
            if not isinstance(raw_epoch, str):
                raise ValueError("stored user turn epoch must be an ISO timestamp")
            return cls(
                turn_id=str(value.get("turn_id") or ""),
                role=role,
                text=str(value.get("text") or ""),
                at=at,
                focus=normalize_sky_chat_focus(value.get("focus")),
                epoch=datetime.fromisoformat(raw_epoch.replace("Z", "+00:00")),
            )
        return cls(
            turn_id=str(value.get("turn_id") or ""),
            role=role,
            text=str(value.get("text") or ""),
            at=at,
            status=str(value.get("status") or ""),
        )


@dataclass(frozen=True, slots=True)
class SkyChatThread:
    """One authenticated user's fingerprinted civil-day dialogue."""

    thread_id: str
    user_id: str
    cache_date: str
    natal_fingerprint: str
    turns: tuple[SkyChatTurn, ...] = ()
    pending_turn_id: str | None = None
    success_count: int = 0

    def __post_init__(self) -> None:
        _canonical_token(self.thread_id, "thread_id")
        _thread_key(self.user_id, self.cache_date, self.natal_fingerprint)
        if not isinstance(self.turns, tuple) or any(
            not isinstance(turn, SkyChatTurn) for turn in self.turns
        ):
            raise ValueError("turns must be a tuple of SkyChatTurn values")
        if (
            not isinstance(self.success_count, int)
            or isinstance(self.success_count, bool)
            or self.success_count < 0
        ):
            raise ValueError("success_count must be a non-negative integer")
        ready_count = sum(
            turn.role == "assistant" and turn.status == "ready"
            for turn in self.turns
        )
        if ready_count != self.success_count:
            raise ValueError("success_count disagrees with ready assistant turns")
        if self.pending_turn_id is not None:
            _canonical_token(self.pending_turn_id, "pending_turn_id")
            pending = [
                turn
                for turn in self.turns
                if turn.turn_id == self.pending_turn_id and turn.role == "user"
            ]
            answered = [
                turn
                for turn in self.turns
                if turn.turn_id == self.pending_turn_id and turn.role == "assistant"
            ]
            if len(pending) != 1 or answered:
                raise ValueError("pending_turn_id must identify one unanswered user turn")

    @property
    def status(self) -> str:
        if self.pending_turn_id is not None:
            return "pending"
        for turn in reversed(self.turns):
            if turn.role == "assistant":
                return turn.status
        return "none"

    @property
    def latest_user_turn(self) -> SkyChatTurn | None:
        return next(
            (turn for turn in reversed(self.turns) if turn.role == "user"),
            None,
        )


class SkyChatStore(Protocol):
    def get(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> SkyChatThread | None:
        ...

    def get_by_thread_id(
        self,
        user_id: str,
        thread_id: str,
    ) -> SkyChatThread | None:
        ...

    def success_count_for_day(self, user_id: str, cache_date: str) -> int:
        ...

    def ensure_thread(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> SkyChatThread:
        ...

    def append_user_turn(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn: SkyChatTurn,
    ) -> SkyChatThread:
        ...

    def mark_ready(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn_id: str,
        reply: GeneratedSkyChatReply,
        *,
        at: datetime,
    ) -> SkyChatThread:
        ...

    def mark_failed(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn_id: str,
        *,
        at: datetime,
    ) -> SkyChatThread:
        ...

    def delete_user(self, user_id: str, *, purge_limits: bool = False) -> None:
        ...


class MemorySkyChatStore:
    """Thread-safe volatile Sky Chat storage for tests and local fallback."""

    def __init__(self) -> None:
        self._threads: dict[tuple[str, str, str], SkyChatThread] = {}
        self._daily_success: dict[tuple[str, str], int] = {}
        self._lock = RLock()

    def get(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> SkyChatThread | None:
        key = _thread_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            return self._threads.get(key)

    def get_by_thread_id(
        self,
        user_id: str,
        thread_id: str,
    ) -> SkyChatThread | None:
        normalized = normalize_user_id(user_id)
        canonical_id = _canonical_token(thread_id, "thread_id")
        with self._lock:
            return next(
                (
                    thread
                    for thread in self._threads.values()
                    if thread.user_id == normalized and thread.thread_id == canonical_id
                ),
                None,
            )

    def success_count_for_day(self, user_id: str, cache_date: str) -> int:
        key = (normalize_user_id(user_id), _canonical_cache_date(cache_date))
        with self._lock:
            return self._daily_success.get(key, 0)

    def ensure_thread(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> SkyChatThread:
        key = _thread_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            current = self._threads.get(key)
            if current is None:
                current = SkyChatThread(_new_id(), *key)
                self._threads[key] = current
            return current

    def append_user_turn(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn: SkyChatTurn,
    ) -> SkyChatThread:
        if not isinstance(turn, SkyChatTurn) or turn.role != "user":
            raise TypeError("turn must be a user SkyChatTurn")
        key = _thread_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            if self._daily_success.get(key[:2], 0) >= SKY_CHAT_MAX_REPLIES_PER_DAY:
                raise SkyChatRateLimitError("Sky Chat civil-day reply limit reached")
            current = self._threads.get(key)
            if current is None:
                current = SkyChatThread(_new_id(), *key)
            updated = _thread_with_user_turn(current, turn)
            self._threads[key] = updated
            return updated

    def mark_ready(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn_id: str,
        reply: GeneratedSkyChatReply,
        *,
        at: datetime,
    ) -> SkyChatThread:
        if not isinstance(reply, GeneratedSkyChatReply):
            raise TypeError("reply must be GeneratedSkyChatReply")
        return self._complete(
            user_id,
            cache_date,
            natal_fingerprint,
            turn_id,
            text=reply.reply,
            status="ready",
            at=at,
        )

    def mark_failed(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn_id: str,
        *,
        at: datetime,
    ) -> SkyChatThread:
        return self._complete(
            user_id,
            cache_date,
            natal_fingerprint,
            turn_id,
            text="",
            status="failed",
            at=at,
        )

    def _complete(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn_id: str,
        *,
        text: str,
        status: str,
        at: datetime,
    ) -> SkyChatThread:
        key = _thread_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            current = self._threads.get(key)
            if current is None:
                raise SkyChatStoreError("Sky Chat pending thread disappeared")
            if (
                status == "ready"
                and self._daily_success.get(key[:2], 0)
                >= SKY_CHAT_MAX_REPLIES_PER_DAY
            ):
                raise SkyChatRateLimitError("Sky Chat civil-day reply limit reached")
            updated = _thread_with_assistant_turn(
                current,
                turn_id,
                text=text,
                status=status,
                at=at,
            )
            self._threads[key] = updated
            if status == "ready":
                self._daily_success[key[:2]] = self._daily_success.get(key[:2], 0) + 1
            return updated

    def delete_user(self, user_id: str, *, purge_limits: bool = False) -> None:
        normalized = normalize_user_id(user_id)
        with self._lock:
            for key in tuple(self._threads):
                if key[0] == normalized:
                    self._threads.pop(key, None)
            if purge_limits:
                for key in tuple(self._daily_success):
                    if key[0] == normalized:
                        self._daily_success.pop(key, None)

    def close(self) -> None:
        return None


_SKY_CHAT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sky_chat_threads (
    user_id TEXT NOT NULL,
    cache_date TEXT NOT NULL,
    natal_fingerprint TEXT NOT NULL,
    thread_id TEXT NOT NULL UNIQUE,
    turns_json TEXT NOT NULL DEFAULT '[]',
    pending_turn_id TEXT,
    success_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, cache_date, natal_fingerprint)
);
CREATE INDEX IF NOT EXISTS sky_chat_threads_user_date_idx
ON sky_chat_threads(user_id, cache_date);
CREATE TABLE IF NOT EXISTS sky_chat_daily_usage (
    user_id TEXT NOT NULL,
    cache_date TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, cache_date)
);
"""


class SQLiteSkyChatStore:
    """Lazy private SQLite store compatible with the shared Railway volume."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser()
        self._connection: sqlite3.Connection | None = None
        self._lock = RLock()
        self._closed = False

    def _connect(self) -> sqlite3.Connection:
        if self._closed:
            raise SkyChatStoreError("Sky Chat storage is closed")
        if self._connection is not None:
            return self._connection
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            with connection:
                connection.executescript(_SKY_CHAT_TABLE_SQL)
        except sqlite3.Error as exc:
            raise SkyChatStoreError("Sky Chat storage is unavailable") from exc
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
    ) -> SkyChatThread | None:
        key = _thread_key(user_id, cache_date, natal_fingerprint)
        with self._lock:
            try:
                row = self._connect().execute(
                    "SELECT * FROM sky_chat_threads "
                    "WHERE user_id = ? AND cache_date = ? AND natal_fingerprint = ?",
                    key,
                ).fetchone()
            except sqlite3.Error as exc:
                raise SkyChatStoreError("Sky Chat storage is unavailable") from exc
        return None if row is None else self._row_to_thread(row)

    def get_by_thread_id(
        self,
        user_id: str,
        thread_id: str,
    ) -> SkyChatThread | None:
        normalized = normalize_user_id(user_id)
        canonical_id = _canonical_token(thread_id, "thread_id")
        with self._lock:
            try:
                row = self._connect().execute(
                    "SELECT * FROM sky_chat_threads "
                    "WHERE user_id = ? AND thread_id = ?",
                    (normalized, canonical_id),
                ).fetchone()
            except sqlite3.Error as exc:
                raise SkyChatStoreError("Sky Chat storage is unavailable") from exc
        return None if row is None else self._row_to_thread(row)

    def success_count_for_day(self, user_id: str, cache_date: str) -> int:
        key = (normalize_user_id(user_id), _canonical_cache_date(cache_date))
        with self._lock:
            try:
                row = self._connect().execute(
                    "SELECT success_count FROM sky_chat_daily_usage "
                    "WHERE user_id = ? AND cache_date = ?",
                    key,
                ).fetchone()
            except sqlite3.Error as exc:
                raise SkyChatStoreError("Sky Chat storage is unavailable") from exc
        return 0 if row is None else int(row["success_count"])

    def ensure_thread(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
    ) -> SkyChatThread:
        key = _thread_key(user_id, cache_date, natal_fingerprint)
        thread_id = _new_id()
        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    connection.execute(
                        "INSERT OR IGNORE INTO sky_chat_threads "
                        "(user_id, cache_date, natal_fingerprint, thread_id) "
                        "VALUES (?, ?, ?, ?)",
                        (*key, thread_id),
                    )
                row = connection.execute(
                    "SELECT * FROM sky_chat_threads "
                    "WHERE user_id = ? AND cache_date = ? AND natal_fingerprint = ?",
                    key,
                ).fetchone()
            except sqlite3.Error as exc:
                raise SkyChatStoreError("Sky Chat storage is unavailable") from exc
        if row is None:
            raise SkyChatStoreError("Sky Chat thread could not be created")
        return self._row_to_thread(row)

    def append_user_turn(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn: SkyChatTurn,
    ) -> SkyChatThread:
        if not isinstance(turn, SkyChatTurn) or turn.role != "user":
            raise TypeError("turn must be a user SkyChatTurn")
        key = _thread_key(user_id, cache_date, natal_fingerprint)

        def mutate(current: SkyChatThread) -> SkyChatThread:
            return _thread_with_user_turn(current, turn)

        return self._mutate(key, mutate, enforce_day_limit=True)

    def mark_ready(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn_id: str,
        reply: GeneratedSkyChatReply,
        *,
        at: datetime,
    ) -> SkyChatThread:
        if not isinstance(reply, GeneratedSkyChatReply):
            raise TypeError("reply must be GeneratedSkyChatReply")
        key = _thread_key(user_id, cache_date, natal_fingerprint)
        return self._mutate(
            key,
            lambda current: _thread_with_assistant_turn(
                current,
                turn_id,
                text=reply.reply,
                status="ready",
                at=at,
            ),
            enforce_day_limit=True,
            increment_usage=True,
        )

    def mark_failed(
        self,
        user_id: str,
        cache_date: str,
        natal_fingerprint: str,
        turn_id: str,
        *,
        at: datetime,
    ) -> SkyChatThread:
        key = _thread_key(user_id, cache_date, natal_fingerprint)
        return self._mutate(
            key,
            lambda current: _thread_with_assistant_turn(
                current,
                turn_id,
                text="",
                status="failed",
                at=at,
            ),
        )

    def delete_user(self, user_id: str, *, purge_limits: bool = False) -> None:
        normalized = normalize_user_id(user_id)
        with self._lock:
            try:
                connection = self._connect()
                with connection:
                    connection.execute(
                        "DELETE FROM sky_chat_threads WHERE user_id = ?",
                        (normalized,),
                    )
                    if purge_limits:
                        connection.execute(
                            "DELETE FROM sky_chat_daily_usage WHERE user_id = ?",
                            (normalized,),
                        )
            except sqlite3.Error as exc:
                raise SkyChatStoreError("Sky Chat storage is unavailable") from exc

    def _mutate(
        self,
        key: tuple[str, str, str],
        operation: Callable[[SkyChatThread], SkyChatThread],
        *,
        enforce_day_limit: bool = False,
        increment_usage: bool = False,
    ) -> SkyChatThread:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM sky_chat_threads "
                    "WHERE user_id = ? AND cache_date = ? AND natal_fingerprint = ?",
                    key,
                ).fetchone()
                if row is None:
                    connection.rollback()
                    raise SkyChatStoreError("Sky Chat thread disappeared")
                usage = connection.execute(
                    "SELECT success_count FROM sky_chat_daily_usage "
                    "WHERE user_id = ? AND cache_date = ?",
                    key[:2],
                ).fetchone()
                daily_success = 0 if usage is None else int(usage["success_count"])
                if enforce_day_limit and daily_success >= SKY_CHAT_MAX_REPLIES_PER_DAY:
                    connection.rollback()
                    raise SkyChatRateLimitError("Sky Chat civil-day reply limit reached")
                updated = operation(self._row_to_thread(row))
                connection.execute(
                    "UPDATE sky_chat_threads SET turns_json = ?, "
                    "pending_turn_id = ?, success_count = ? "
                    "WHERE user_id = ? AND cache_date = ? AND natal_fingerprint = ?",
                    (
                        _turns_json(updated.turns),
                        updated.pending_turn_id,
                        updated.success_count,
                        *key,
                    ),
                )
                if increment_usage:
                    connection.execute(
                        "INSERT INTO sky_chat_daily_usage "
                        "(user_id, cache_date, success_count) VALUES (?, ?, 1) "
                        "ON CONFLICT(user_id, cache_date) DO UPDATE SET "
                        "success_count = success_count + 1",
                        key[:2],
                    )
                connection.commit()
                return updated
            except (SkyChatError, TypeError, ValueError):
                if connection.in_transaction:
                    connection.rollback()
                raise
            except sqlite3.Error as exc:
                if connection.in_transaction:
                    connection.rollback()
                raise SkyChatStoreError("Sky Chat storage is unavailable") from exc

    @staticmethod
    def _row_to_thread(row: sqlite3.Row) -> SkyChatThread:
        try:
            decoded = json.loads(str(row["turns_json"]))
            if not isinstance(decoded, list):
                raise ValueError("turns_json must be an array")
            turns = tuple(SkyChatTurn.from_storage_dict(item) for item in decoded)
            pending = row["pending_turn_id"]
            return SkyChatThread(
                thread_id=str(row["thread_id"]),
                user_id=str(row["user_id"]),
                cache_date=str(row["cache_date"]),
                natal_fingerprint=str(row["natal_fingerprint"]),
                turns=turns,
                pending_turn_id=None if pending is None else str(pending),
                success_count=int(row["success_count"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SkyChatStoreError("Sky Chat storage is invalid") from exc


@dataclass(frozen=True, slots=True)
class _SkyChatJob:
    record: NatalRecord
    user_id: str
    cache_date: str
    natal_fingerprint: str
    turn_id: str
    facts: Mapping[str, Any]
    message: str


class _SkyChatQueue:
    """Bounded daemon queue with turn de-duplication and serial execution."""

    def __init__(
        self,
        worker: Callable[[_SkyChatJob], None],
        *,
        maxsize: int = 256,
    ) -> None:
        if not callable(worker):
            raise TypeError("worker must be callable")
        if not isinstance(maxsize, int) or isinstance(maxsize, bool) or maxsize <= 0:
            raise ValueError("maxsize must be a positive integer")
        self._worker = worker
        self._jobs: queue.Queue[_SkyChatJob] = queue.Queue(maxsize=maxsize)
        self._condition = Condition(RLock())
        self._pending_turns: set[str] = set()
        self._pending_users: dict[str, _SkyChatJob] = {}
        self._started = False
        self._closed = False
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("Sky Chat queue is closed")
            if self._started:
                return
            self._started = True
            self._thread = Thread(
                target=self._run,
                name="sidereal-sky-chat",
                daemon=True,
            )
            self._thread.start()

    def enqueue(self, job: _SkyChatJob) -> bool:
        if not isinstance(job, _SkyChatJob):
            raise TypeError("job must be a Sky Chat job")
        with self._condition:
            if not self._started or self._closed:
                raise SkyChatError("Sky Chat queue is unavailable")
            if job.turn_id in self._pending_turns:
                return False
            if job.user_id in self._pending_users:
                raise SkyChatPendingError("one Sky Chat job is already pending for this user")
            self._pending_turns.add(job.turn_id)
            self._pending_users[job.user_id] = job
            try:
                self._jobs.put_nowait(job)
            except queue.Full as exc:
                self._pending_turns.remove(job.turn_id)
                self._pending_users.pop(job.user_id, None)
                raise SkyChatError("Sky Chat queue is full") from exc
            self._condition.notify_all()
            return True

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0.0:
            raise ValueError("timeout_seconds must be finite and non-negative")
        with self._condition:
            return self._condition.wait_for(
                lambda: not self._pending_turns,
                timeout=float(timeout_seconds),
            )

    def contains(self, turn_id: str) -> bool:
        canonical = _canonical_token(turn_id, "turn_id")
        with self._condition:
            return canonical in self._pending_turns

    def pending_job(self, user_id: str) -> _SkyChatJob | None:
        normalized = normalize_user_id(user_id)
        with self._condition:
            return self._pending_users.get(normalized)

    def discard_user(self, user_id: str) -> None:
        normalized = normalize_user_id(user_id)
        with self._condition:
            job = self._pending_users.pop(normalized, None)
            if job is not None:
                self._pending_turns.discard(job.turn_id)
            self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            while True:
                try:
                    job = self._jobs.get_nowait()
                except queue.Empty:
                    break
                self._jobs.task_done()
                self._release_locked(job)
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
            except Exception as exc:
                _LOGGER.warning("Private Sky Chat worker failed (%s)", type(exc).__name__)
            finally:
                self._jobs.task_done()
                with self._condition:
                    self._release_locked(job)
                    self._condition.notify_all()

    def _release_locked(self, job: _SkyChatJob) -> None:
        self._pending_turns.discard(job.turn_id)
        current = self._pending_users.get(job.user_id)
        if current is not None and current.turn_id == job.turn_id:
            self._pending_users.pop(job.user_id, None)


SkyChatFactsBuilder = Callable[..., dict[str, Any]]
SkyChatClock = Callable[[], datetime]


class SkyChatService:
    """Coordinate private day threads, focus facts, rate limits, and authorship."""

    def __init__(
        self,
        store: SkyChatStore,
        facts_builder: SkyChatFactsBuilder,
        *,
        author: SkyChatAuthor | None = None,
        clock: SkyChatClock = lambda: datetime.now(UTC).replace(microsecond=0),
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
        self._queue = (
            None if author is None else _SkyChatQueue(self._run_job, maxsize=queue_size)
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

    def post(
        self,
        record: NatalRecord,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(record, NatalRecord):
            raise TypeError("record must be a NatalRecord")
        if not isinstance(payload, Mapping):
            raise SkyChatValidationError("Sky Chat request body must be an object")
        allowed = frozenset(("message", "focus", "thread_id", "when", "tz"))
        extras = sorted(set(payload) - allowed)
        if extras:
            raise SkyChatValidationError(
                f"unsupported Sky Chat field(s): {', '.join(str(item) for item in extras)}"
            )
        message = validate_sky_chat_message(payload.get("message"))
        focus = normalize_sky_chat_focus(payload.get("focus"))
        _validate_client_thread_id(payload.get("thread_id"))
        received_at = _aware_utc(self._clock(), "clock result")
        instant = _resolve_request_instant(
            record,
            payload.get("when"),
            payload.get("tz"),
            default=received_at,
        )
        cache_date = transit_essay_cache_date(record, instant)
        if cache_date != transit_essay_cache_date(record, received_at):
            raise SkyChatValidationError(
                "when must fall within the current natal civil day"
            )
        fingerprint = natal_fingerprint(record)
        current = self._store.get(record.user_id, cache_date, fingerprint)
        daily_success = self._store.success_count_for_day(record.user_id, cache_date)
        if self._queue is None:
            return _chat_envelope(
                current,
                status="unavailable",
                cache_date=cache_date,
                focus=focus,
                day_success_count=daily_success,
            )
        if daily_success >= SKY_CHAT_MAX_REPLIES_PER_DAY:
            return _chat_envelope(
                current,
                status="limited",
                cache_date=cache_date,
                day_success_count=daily_success,
            )
        if current is None:
            current = self._store.ensure_thread(record.user_id, cache_date, fingerprint)
        if current.pending_turn_id is not None:
            self._ensure_pending_job(record, current)
            refreshed = self._store.get(record.user_id, cache_date, fingerprint) or current
            return _chat_envelope(
                refreshed,
                cache_date=cache_date,
                day_success_count=self._store.success_count_for_day(
                    record.user_id, cache_date
                ),
            )
        busy_job = self._queue.pending_job(record.user_id)
        if busy_job is not None:
            busy_thread = self._store.get(
                busy_job.user_id,
                busy_job.cache_date,
                busy_job.natal_fingerprint,
            )
            if busy_thread is not None:
                return _chat_envelope(
                    busy_thread,
                    cache_date=busy_thread.cache_date,
                    day_success_count=self._store.success_count_for_day(
                        busy_thread.user_id, busy_thread.cache_date
                    ),
                )
            self._queue.discard_user(record.user_id)

        facts = self._facts_builder(record, focus, when=instant)
        _validate_fact_packet(facts, cache_date, focus)
        turn = SkyChatTurn(
            turn_id=_new_id(),
            role="user",
            text=message,
            at=received_at,
            focus=focus,
            epoch=instant,
        )
        try:
            pending = self._store.append_user_turn(
                record.user_id,
                cache_date,
                fingerprint,
                turn,
            )
        except SkyChatPendingError:
            latest = self._store.get(record.user_id, cache_date, fingerprint)
            if latest is None:
                raise SkyChatStoreError("Sky Chat pending thread disappeared")
            self._ensure_pending_job(record, latest)
            return _chat_envelope(
                latest,
                cache_date=cache_date,
                day_success_count=self._store.success_count_for_day(
                    record.user_id, cache_date
                ),
            )
        except SkyChatRateLimitError:
            latest = self._store.get(record.user_id, cache_date, fingerprint)
            return _chat_envelope(
                latest,
                status="limited",
                cache_date=cache_date,
                day_success_count=self._store.success_count_for_day(
                    record.user_id, cache_date
                ),
            )
        try:
            self._queue.enqueue(
                _SkyChatJob(
                    record=record,
                    user_id=record.user_id,
                    cache_date=cache_date,
                    natal_fingerprint=fingerprint,
                    turn_id=turn.turn_id,
                    facts=facts,
                    message=message,
                )
            )
        except SkyChatPendingError:
            return _chat_envelope(
                pending,
                cache_date=cache_date,
                day_success_count=self._store.success_count_for_day(
                    record.user_id, cache_date
                ),
            )
        except SkyChatError:
            failed = self._store.mark_failed(
                record.user_id,
                cache_date,
                fingerprint,
                turn.turn_id,
                at=_aware_utc(self._clock(), "clock result"),
            )
            return _chat_envelope(
                failed,
                cache_date=cache_date,
                day_success_count=self._store.success_count_for_day(
                    record.user_id, cache_date
                ),
            )
        latest = self._store.get(record.user_id, cache_date, fingerprint) or pending
        return _chat_envelope(
            latest,
            cache_date=cache_date,
            day_success_count=self._store.success_count_for_day(
                record.user_id, cache_date
            ),
        )

    def get(
        self,
        record: NatalRecord,
        *,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(record, NatalRecord):
            raise TypeError("record must be a NatalRecord")
        _validate_client_thread_id(thread_id)
        instant = _aware_utc(self._clock(), "clock result")
        today_cache_date = transit_essay_cache_date(record, instant)
        fingerprint = natal_fingerprint(record)
        current: SkyChatThread | None = None
        if thread_id is not None and _TOKEN_RE.fullmatch(thread_id.strip()) is not None:
            selected = self._store.get_by_thread_id(record.user_id, thread_id.strip())
            if selected is not None and selected.natal_fingerprint == fingerprint:
                current = selected
        if current is None:
            current = self._store.get(record.user_id, today_cache_date, fingerprint)
        cache_date = current.cache_date if current is not None else today_cache_date
        daily_success = self._store.success_count_for_day(record.user_id, cache_date)
        if self._queue is None:
            return _chat_envelope(
                current,
                status="unavailable",
                cache_date=cache_date,
                day_success_count=daily_success,
            )
        if current is not None and current.pending_turn_id is not None:
            self._ensure_pending_job(record, current)
            current = (
                self._store.get(
                    current.user_id,
                    current.cache_date,
                    current.natal_fingerprint,
                )
                or current
            )
            daily_success = self._store.success_count_for_day(
                record.user_id, cache_date
            )
        return _chat_envelope(
            current,
            cache_date=cache_date,
            day_success_count=daily_success,
        )

    def invalidate_user(self, user_id: str, *, purge_limits: bool = False) -> None:
        normalized = normalize_user_id(user_id)
        if self._queue is not None:
            self._queue.discard_user(normalized)
        self._store.delete_user(
            normalized,
            purge_limits=purge_limits,
        )

    def wait_until_idle(self, timeout_seconds: float = 5.0) -> bool:
        return (
            True
            if self._queue is None
            else self._queue.wait_until_idle(timeout_seconds)
        )

    def _ensure_pending_job(
        self,
        record: NatalRecord,
        thread: SkyChatThread,
    ) -> None:
        assert self._queue is not None and thread.pending_turn_id is not None
        if self._queue.contains(thread.pending_turn_id):
            return
        user_turn = next(
            turn
            for turn in thread.turns
            if turn.role == "user" and turn.turn_id == thread.pending_turn_id
        )
        assert user_turn.focus is not None and user_turn.epoch is not None
        try:
            facts = self._facts_builder(record, user_turn.focus, when=user_turn.epoch)
            _validate_fact_packet(facts, thread.cache_date, user_turn.focus)
            self._queue.enqueue(
                _SkyChatJob(
                    record=record,
                    user_id=thread.user_id,
                    cache_date=thread.cache_date,
                    natal_fingerprint=thread.natal_fingerprint,
                    turn_id=user_turn.turn_id,
                    facts=facts,
                    message=user_turn.text,
                )
            )
        except SkyChatPendingError:
            return
        except Exception as exc:
            _LOGGER.warning(
                "Sky Chat pending job setup failed (%s)",
                type(exc).__name__,
            )
            try:
                self._store.mark_failed(
                    thread.user_id,
                    thread.cache_date,
                    thread.natal_fingerprint,
                    user_turn.turn_id,
                    at=_aware_utc(self._clock(), "clock result"),
                )
            except SkyChatError as store_exc:
                _LOGGER.warning(
                    "Sky Chat pending failure could not be stored (%s)",
                    type(store_exc).__name__,
                )

    def _run_job(self, job: _SkyChatJob) -> None:
        assert self._author is not None
        completed: SkyChatThread | None = None
        try:
            if (
                self._store.success_count_for_day(job.user_id, job.cache_date)
                >= SKY_CHAT_MAX_REPLIES_PER_DAY
            ):
                raise SkyChatRateLimitError("Sky Chat civil-day reply limit reached")
            current = self._store.get(
                job.user_id,
                job.cache_date,
                job.natal_fingerprint,
            )
            if current is None:
                raise SkyChatStoreError("Sky Chat thread disappeared")
            if current.pending_turn_id != job.turn_id or not any(
                turn.role == "user" and turn.turn_id == job.turn_id
                for turn in current.turns
            ):
                _LOGGER.warning("Stale private Sky Chat job was dropped")
                return
            history = _thread_history(current, before_turn_id=job.turn_id)
            content = self._author.generate(job.facts, history, job.message)
            if not isinstance(content, GeneratedSkyChatReply):
                raise SkyChatValidationError("Sky Chat author returned an invalid result type")
            content = validate_sky_chat_reply(content.to_dict(), job.facts)
            completed = self._store.mark_ready(
                job.user_id,
                job.cache_date,
                job.natal_fingerprint,
                job.turn_id,
                content,
                at=_aware_utc(self._clock(), "clock result"),
            )
        except Exception as exc:
            try:
                completed = self._store.mark_failed(
                    job.user_id,
                    job.cache_date,
                    job.natal_fingerprint,
                    job.turn_id,
                    at=_aware_utc(self._clock(), "clock result"),
                )
            except Exception:
                pass
            _LOGGER.warning(
                "Private Sky Chat generation failed (%s)",
                type(exc).__name__,
            )
        if completed is not None and completed.pending_turn_id is not None:
            try:
                self._ensure_pending_job(job.record, completed)
            except Exception as exc:
                _LOGGER.warning(
                    "Private Sky Chat follow-up enqueue failed (%s)",
                    type(exc).__name__,
                )


def sky_chat_service_from_env(
    db_path: Path | str,
    facts_builder: SkyChatFactsBuilder,
) -> SkyChatService:
    """Build persistent-if-available Sky Chat using the shared DeepSeek env."""

    path = Path(db_path).expanduser()
    store: SkyChatStore = (
        SQLiteSkyChatStore(path) if path.is_file() else MemorySkyChatStore()
    )
    raw_key = os.environ.get("DEEPSEEK_API_KEY")
    author = (
        None
        if raw_key is None or not raw_key.strip()
        else DeepSeekSkyChatAuthor.from_env()
    )
    return SkyChatService(store, facts_builder, author=author)


def _chat_envelope(
    thread: SkyChatThread | None,
    *,
    cache_date: str,
    status: str | None = None,
    focus: SkyChatFocus | None = None,
    day_success_count: int | None = None,
) -> dict[str, Any]:
    _canonical_cache_date(cache_date)
    selected_status = status or (thread.status if thread is not None else "none")
    if selected_status not in {
        "pending",
        "ready",
        "failed",
        "unavailable",
        "none",
        "limited",
    }:
        raise ValueError("invalid Sky Chat envelope status")
    latest = thread.latest_user_turn if thread is not None else None
    selected_focus = focus or (latest.focus if latest is not None else None)
    selected_turn_id = latest.turn_id if latest is not None else None
    success_count = (
        thread.success_count
        if day_success_count is None and thread is not None
        else (day_success_count or 0)
    )
    if (
        not isinstance(success_count, int)
        or isinstance(success_count, bool)
        or success_count < 0
    ):
        raise ValueError("day_success_count must be a non-negative integer")
    return {
        "schema_version": SKY_CHAT_SCHEMA_VERSION,
        "type": SKY_CHAT_TYPE,
        "status": selected_status,
        "thread_id": thread.thread_id if thread is not None else None,
        "cache_date": cache_date,
        "turn_id": selected_turn_id,
        "focus": selected_focus.to_dict() if selected_focus is not None else {},
        "turns": (
            [turn.to_api_dict() for turn in thread.turns]
            if thread is not None
            else []
        ),
        "epistemic": SKY_CHAT_EPISTEMIC,
        "remaining_turns": max(0, SKY_CHAT_MAX_REPLIES_PER_DAY - success_count),
    }


def _thread_with_user_turn(
    current: SkyChatThread,
    turn: SkyChatTurn,
) -> SkyChatThread:
    if current.pending_turn_id is not None:
        raise SkyChatPendingError("one Sky Chat turn is already pending")
    if current.success_count >= SKY_CHAT_MAX_REPLIES_PER_DAY:
        raise SkyChatRateLimitError("Sky Chat civil-day reply limit reached")
    return SkyChatThread(
        thread_id=current.thread_id,
        user_id=current.user_id,
        cache_date=current.cache_date,
        natal_fingerprint=current.natal_fingerprint,
        turns=(*current.turns, turn),
        pending_turn_id=current.pending_turn_id or turn.turn_id,
        success_count=current.success_count,
    )


def _thread_with_assistant_turn(
    current: SkyChatThread,
    turn_id: str,
    *,
    text: str,
    status: str,
    at: datetime,
) -> SkyChatThread:
    canonical_turn_id = _canonical_token(turn_id, "turn_id")
    matching_user_index = next(
        (
            index
            for index, turn in enumerate(current.turns)
            if turn.turn_id == canonical_turn_id and turn.role == "user"
        ),
        None,
    )
    if matching_user_index is None or any(
        turn.turn_id == canonical_turn_id and turn.role == "assistant"
        for turn in current.turns
    ):
        raise SkyChatStoreError("Sky Chat pending turn disappeared")
    assistant = SkyChatTurn(
        turn_id=canonical_turn_id,
        role="assistant",
        text=text,
        at=_aware_utc(at, "assistant at"),
        status=status,
    )
    turns = (
        *current.turns[: matching_user_index + 1],
        assistant,
        *current.turns[matching_user_index + 1 :],
    )
    answered = {
        turn.turn_id for turn in turns if turn.role == "assistant"
    }
    if current.pending_turn_id == canonical_turn_id:
        next_pending = next(
            (
                turn.turn_id
                for turn in turns
                if turn.role == "user" and turn.turn_id not in answered
            ),
            None,
        )
    else:
        next_pending = current.pending_turn_id
    return SkyChatThread(
        thread_id=current.thread_id,
        user_id=current.user_id,
        cache_date=current.cache_date,
        natal_fingerprint=current.natal_fingerprint,
        turns=turns,
        pending_turn_id=next_pending,
        success_count=current.success_count + (1 if status == "ready" else 0),
    )


def _thread_history(
    thread: SkyChatThread,
    *,
    before_turn_id: str | None = None,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for turn in thread.turns:
        if before_turn_id is not None and turn.turn_id == before_turn_id and turn.role == "user":
            break
        if turn.role == "assistant" and turn.status != "ready":
            continue
        result.append({"role": turn.role, "text": turn.text})
    return result[-SKY_CHAT_MAX_HISTORY_TURNS:]


def _validated_history(
    value: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError("history must be a sequence")
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"role", "text"}:
            raise SkyChatValidationError("history turns require role and text")
        role = item.get("role")
        text = item.get("text")
        if role not in {"user", "assistant"} or not isinstance(text, str) or not text:
            raise SkyChatValidationError("history turn is invalid")
        result.append({"role": role, "text": text})
    return result


def _validate_fact_packet(
    value: Any,
    cache_date: str,
    focus: SkyChatFocus,
) -> None:
    if not isinstance(value, Mapping):
        raise TypeError("Sky Chat facts builder must return a mapping")
    if value.get("schema_version") != SKY_CHAT_SCHEMA_VERSION:
        raise SkyChatValidationError("Sky Chat facts use an unsupported schema")
    if value.get("type") != SKY_CHAT_FACTS_TYPE:
        raise SkyChatValidationError("Sky Chat facts use an unsupported type")
    if value.get("cache_date") != cache_date:
        raise SkyChatValidationError("Sky Chat facts disagree with the civil day")
    if value.get("focus") != focus.to_dict():
        raise SkyChatValidationError("Sky Chat facts disagree with the selected focus")


def _resolve_request_instant(
    record: NatalRecord,
    raw_when: Any,
    raw_tz: Any,
    *,
    default: datetime,
) -> datetime:
    timezone_name = record.tz
    if raw_tz is not None:
        if not isinstance(raw_tz, str) or not raw_tz.strip():
            raise SkyChatValidationError("tz must be a non-empty IANA timezone")
        selected = raw_tz.strip()
        zone = parse_timezone(selected)
        if selected.upper() not in {"UTC", "Z"} and not isinstance(zone, ZoneInfo):
            raise SkyChatValidationError("tz must be an IANA timezone")
        timezone_name = "UTC" if selected.upper() in {"UTC", "Z"} else zone.key
    if raw_when is None:
        return _aware_utc(default, "default instant")
    if isinstance(raw_when, datetime):
        parsed = raw_when
    elif isinstance(raw_when, str):
        text = raw_when.strip()
        if not text or ("T" not in text and " " not in text):
            raise SkyChatValidationError("when must be an ISO datetime with date and time")
        try:
            parsed = datetime.fromisoformat(
                text[:-1] + "+00:00" if text.upper().endswith("Z") else text
            )
        except ValueError as exc:
            raise SkyChatValidationError("when must be a valid ISO datetime") from exc
    else:
        raise SkyChatValidationError("when must be an ISO datetime string")
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC)
    try:
        return resolve_moment(
            MomentInput(
                local_date=parsed.date(),
                local_time=parsed.time(),
                tz=timezone_name,
                label="Sky Chat",
                fold=parsed.fold if parsed.fold == 1 else None,
            )
        ).utc_datetime
    except ValueError as exc:
        raise SkyChatValidationError(str(exc)) from exc


def _validate_reply_aspects(reply: str, facts: Mapping[str, Any]) -> None:
    allowed = {
        (
            str(item.get("transit_body") or ""),
            str(item.get("aspect_id") or ""),
            str(item.get("natal_point") or ""),
        )
        for item in _list_items(facts.get("aspects"))
    }
    matches = (
        *_FORMAL_ASPECT_RE.finditer(reply),
        *_PAIR_ASPECT_RE.finditer(reply),
        *_BETWEEN_ASPECT_RE.finditer(reply),
        *_COPULAR_ASPECT_RE.finditer(reply),
        *_FROM_ASPECT_RE.finditer(reply),
        *_LINK_ASPECT_RE.finditer(reply),
        *_PAIR_CONNECTION_ASPECT_RE.finditer(reply),
    )
    for match in matches:
        claim = (
            _normalized_body_reference(match.group("transit")),
            _normalized_aspect_reference(match.group("aspect")),
            _normalized_body_reference(match.group("natal")),
        )
        if claim not in allowed:
            raise SkyChatValidationError(
                "Sky Chat reply mentions an aspect absent from the facts"
            )
    for match in _UNLABELED_PAIR_ASPECT_RE.finditer(reply):
        claim = (
            _normalized_body_reference(match.group("transit")),
            _normalized_aspect_reference(match.group("aspect")),
            _normalized_body_reference(match.group("natal")),
        )
        reverse = (claim[2], claim[1], claim[0])
        if claim not in allowed and reverse not in allowed:
            raise SkyChatValidationError(
                "Sky Chat reply mentions an aspect absent from the facts"
            )
    # Catch alternate prose orderings without trying to parse free language in
    # full. Explicit transit/natal role labels plus an aspect word constitute a
    # geometry claim; pair each aspect with the nearest labeled endpoints.
    for clause in _CHAT_CLAUSE_SPLIT_RE.split(reply):
        transit_mentions = tuple(_EXPLICIT_TRANSIT_RE.finditer(clause))
        natal_mentions = tuple(_EXPLICIT_NATAL_RE.finditer(clause))
        if not transit_mentions or not natal_mentions:
            continue
        for aspect_match in _ASPECT_LEXEME_RE.finditer(clause):
            transit_match = min(
                transit_mentions,
                key=lambda item: abs(item.start() - aspect_match.start()),
            )
            natal_match = min(
                natal_mentions,
                key=lambda item: abs(item.start() - aspect_match.start()),
            )
            claim = (
                _normalized_body_reference(transit_match.group("body")),
                _normalized_aspect_reference(aspect_match.group("aspect")),
                _normalized_body_reference(natal_match.group("body")),
            )
            if claim not in allowed:
                raise SkyChatValidationError(
                    "Sky Chat reply mentions an aspect absent from the facts"
                )
    allowed_types = {item[1] for item in allowed}
    for aspect_match in _ASPECT_LEXEME_RE.finditer(reply):
        if _normalized_aspect_reference(aspect_match.group("aspect")) not in allowed_types:
            raise SkyChatValidationError(
                "Sky Chat reply mentions an aspect absent from the facts"
            )


def _validate_reply_placements_and_motion(
    reply: str,
    facts: Mapping[str, Any],
) -> None:
    movers = _list_items(facts.get("movers_short"))
    natal = _list_items(facts.get("natal_placements_short"))
    transit_placements = {
        (str(item.get("body") or ""), str(item.get("sign") or "").casefold())
        for item in movers
    }
    natal_placements = {
        (str(item.get("body") or ""), str(item.get("sign") or "").casefold())
        for item in natal
    }
    for match in (
        *_BODY_IN_SIGN_RE.finditer(reply),
        *_BODY_ENTERS_SIGN_RE.finditer(reply),
        *_BODY_OCCUPIES_SIGN_RE.finditer(reply),
        *_SIGN_CONTAINS_BODY_RE.finditer(reply),
        *_SIGN_OCCUPIED_BY_BODY_RE.finditer(reply),
    ):
        claim = (
            _normalized_body_reference(match.group("body")),
            match.group("sign").casefold(),
        )
        role = (match.group("role") or "").casefold()
        allowed = (
            transit_placements
            if role.startswith("transit")
            else natal_placements
            if role == "natal"
            else transit_placements | natal_placements
        )
        if claim not in allowed:
            raise SkyChatValidationError(
                "Sky Chat reply mentions a placement absent from the facts"
            )

    transit_degrees = {
        (str(item.get("body") or ""), str(item.get("sign") or "").casefold()): item.get(
            "degree_in_sign"
        )
        for item in movers
    }
    natal_degrees = {
        (str(item.get("body") or ""), str(item.get("sign") or "").casefold()): item.get(
            "degree_in_sign"
        )
        for item in natal
    }
    for match in _BODY_AT_SIGN_DEGREE_RE.finditer(reply):
        claim = (
            _normalized_body_reference(match.group("body")),
            match.group("sign").casefold(),
        )
        role = (match.group("role") or "").casefold()
        allowed_degrees = (
            transit_degrees
            if role.startswith("transit")
            else natal_degrees
            if role == "natal"
            else {**natal_degrees, **transit_degrees}
        )
        expected_degree = allowed_degrees.get(claim)
        claimed_degree = float(match.group("degree"))
        if (
            not isinstance(expected_degree, (int, float))
            or isinstance(expected_degree, bool)
            or abs(float(expected_degree) - claimed_degree) > 0.1
        ):
            raise SkyChatValidationError(
                "Sky Chat reply mentions a placement absent from the facts"
            )

    transit_motion = {
        str(item.get("body") or ""): item.get("retro")
        for item in movers
        if item.get("retro") in {True, False}
    }
    natal_motion = {
        str(item.get("body") or ""): item.get("retro")
        for item in natal
        if item.get("retro") in {True, False}
    }
    for match in _BODY_MOTION_RE.finditer(reply):
        body = _normalized_body_reference(match.group("body"))
        role = (match.group("role") or "").casefold()
        motion = re.sub(r"\s+", " ", match.group("motion").casefold())
        expected_retro = motion in {
            "retro",
            "retrograde",
            "backward",
            "backwards",
            "moving backward",
            "moving backwards",
        }
        allowed_motion = (
            transit_motion
            if role.startswith("transit")
            else natal_motion
            if role == "natal"
            else None
        )
        grounded = (
            body in allowed_motion
            and bool(allowed_motion[body]) == expected_retro
            if allowed_motion is not None
            else (
                body in transit_motion
                and bool(transit_motion[body]) == expected_retro
            )
            or (
                body in natal_motion
                and bool(natal_motion[body]) == expected_retro
            )
        )
        if not grounded:
            raise SkyChatValidationError(
                "Sky Chat reply mentions motion absent from the facts"
            )

    focus_aspect = facts.get("focus_aspect")
    all_aspects = _list_items(facts.get("aspects"))
    aspect_lookup = {
        (
            str(item.get("transit_body") or ""),
            str(item.get("natal_point") or ""),
        ): item
        for item in all_aspects
    }
    for match in _ANGLE_CLAIM_RE.finditer(reply):
        contact = aspect_lookup.get(
            (
                _normalized_body_reference(match.group("transit")),
                _normalized_body_reference(match.group("natal")),
            )
        )
        separation = None if contact is None else contact.get("separation")
        if (
            not isinstance(separation, (int, float))
            or isinstance(separation, bool)
            or abs(float(separation) - float(match.group("separation"))) > 0.6
        ):
            raise SkyChatValidationError(
                "Sky Chat reply mentions geometry absent from the facts"
            )
    for clause in _CHAT_CLAUSE_SPLIT_RE.split(reply):
        claimed_spans = _claimed_aspect_spans(clause, all_aspects)
        fallback_targets = (
            (focus_aspect,)
            if isinstance(focus_aspect, Mapping)
            else all_aspects
            if len(all_aspects) == 1
            else ()
        )
        for match in (
            *_ORB_CLAIM_RE.finditer(clause),
            *_VALUE_ORB_CLAIM_RE.finditer(clause),
            *_FROM_EXACT_CLAIM_RE.finditer(clause),
            *_WIDE_ORB_CLAIM_RE.finditer(clause),
        ):
            targets = _nearest_aspect_targets(
                match,
                claimed_spans,
                fallback_targets,
            )
            claimed_orb = float(match.group("orb"))
            if not any(
                isinstance(item.get("orb"), (int, float))
                and not isinstance(item.get("orb"), bool)
                and abs(float(item["orb"]) - claimed_orb) <= 0.05
                for item in targets
            ):
                raise SkyChatValidationError(
                    "Sky Chat reply mentions an orb absent from the facts"
                )
        for match in _EXACT_CLAIM_RE.finditer(clause):
            targets = _nearest_aspect_targets(
                match,
                claimed_spans,
                fallback_targets,
            )
            if not any(
                isinstance(item.get("orb"), (int, float))
                and not isinstance(item.get("orb"), bool)
                and abs(float(item["orb"])) <= 0.05
                for item in targets
            ):
                raise SkyChatValidationError(
                    "Sky Chat reply mentions exact geometry absent from the facts"
                )
        for match in _PHASE_CLAIM_RE.finditer(clause):
            targets = _nearest_aspect_targets(
                match,
                claimed_spans,
                fallback_targets,
            )
            phase = re.sub(r"\s+", " ", match.group("phase").casefold())
            expected_applying = phase in {"applying", "tightening"}
            if not any(item.get("applying") is expected_applying for item in targets):
                raise SkyChatValidationError(
                    "Sky Chat reply mentions an aspect phase absent from the facts"
                )


def _claimed_aspects_for_text(
    text: str,
    aspects: tuple[Mapping[str, Any], ...],
) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    for item, _start, _end in _claimed_aspect_spans(text, aspects):
        if item not in result:
            result.append(item)
    return tuple(result)


def _claimed_aspect_spans(
    text: str,
    aspects: tuple[Mapping[str, Any], ...],
) -> tuple[tuple[Mapping[str, Any], int, int], ...]:
    lookup = {
        (
            str(item.get("transit_body") or ""),
            str(item.get("aspect_id") or ""),
            str(item.get("natal_point") or ""),
        ): item
        for item in aspects
    }
    found: list[tuple[Mapping[str, Any], int, int]] = []

    def add(match: re.Match[str], *, allow_reverse: bool = False) -> None:
        claim = (
            _normalized_body_reference(match.group("transit")),
            _normalized_aspect_reference(match.group("aspect")),
            _normalized_body_reference(match.group("natal")),
        )
        if claim not in lookup and allow_reverse:
            reverse = (claim[2], claim[1], claim[0])
            if reverse in lookup:
                claim = reverse
        if claim in lookup:
            candidate = (lookup[claim], match.start(), match.end())
            if candidate not in found:
                found.append(candidate)

    for pattern in (
        _FORMAL_ASPECT_RE,
        _PAIR_ASPECT_RE,
        _BETWEEN_ASPECT_RE,
        _COPULAR_ASPECT_RE,
        _FROM_ASPECT_RE,
        _LINK_ASPECT_RE,
        _PAIR_CONNECTION_ASPECT_RE,
    ):
        for match in pattern.finditer(text):
            add(match)
    for match in _UNLABELED_PAIR_ASPECT_RE.finditer(text):
        add(match, allow_reverse=True)

    transit_mentions = tuple(_EXPLICIT_TRANSIT_RE.finditer(text))
    natal_mentions = tuple(_EXPLICIT_NATAL_RE.finditer(text))
    if transit_mentions and natal_mentions:
        for aspect_match in _ASPECT_LEXEME_RE.finditer(text):
            transit_match = min(
                transit_mentions,
                key=lambda item: abs(item.start() - aspect_match.start()),
            )
            natal_match = min(
                natal_mentions,
                key=lambda item: abs(item.start() - aspect_match.start()),
            )
            claim = (
                _normalized_body_reference(transit_match.group("body")),
                _normalized_aspect_reference(aspect_match.group("aspect")),
                _normalized_body_reference(natal_match.group("body")),
            )
            if claim in lookup:
                candidate = (
                    lookup[claim],
                    min(
                        transit_match.start(),
                        natal_match.start(),
                        aspect_match.start(),
                    ),
                    max(
                        transit_match.end(),
                        natal_match.end(),
                        aspect_match.end(),
                    ),
                )
                if candidate not in found:
                    found.append(candidate)
    return tuple(sorted(found, key=lambda item: (item[1], item[2])))


def _nearest_aspect_targets(
    claim: re.Match[str],
    aspect_spans: tuple[tuple[Mapping[str, Any], int, int], ...],
    fallback: tuple[Mapping[str, Any], ...],
) -> tuple[Mapping[str, Any], ...]:
    if not aspect_spans:
        return fallback

    # Orb and phase prose normally follows the contact it qualifies. Prefer the
    # nearest preceding contact even when the next contact starts soon after a
    # comma ("... is applying, while Venus trine Sun ..."). Only use a following
    # contact for constructions that put the numeric claim first.
    preceding = tuple(item for item in aspect_spans if item[2] <= claim.start())
    if preceding:
        ranked = tuple(
            (claim.start() - end, item)
            for item, _start, end in preceding
        )
    else:
        following = tuple(item for item in aspect_spans if item[1] >= claim.end())
        if not following:
            return fallback
        ranked = tuple(
            (start - claim.end(), item)
            for item, start, _end in following
        )
    closest = min(distance for distance, _item in ranked)
    result: list[Mapping[str, Any]] = []
    for distance, item in ranked:
        if distance == closest and item not in result:
            result.append(item)
    return tuple(result)


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


def _placement_fact(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "body": str(value["body"]),
        "sign": str(value["sign"]),
        "degree_in_sign": _finite_number(value["degree_in_sign"]),
    }
    if "retro" in value:
        result["retro"] = bool(value["retro"])
    if "house" in value:
        result["house"] = int(value["house"])
    if "natal_house" in value:
        result["natal_house"] = int(value["natal_house"])
    return result


def _delta_fact(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "body": str(value["body"]),
        "delta_deg": _finite_number(value["delta_deg"]),
    }


def _chat_aspect_fact(value: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "transit_body": str(value["transit_body"]),
        "natal_point": str(value["natal_point"]),
        "aspect_id": str(value["aspect_id"]),
        "separation": _finite_number(value["separation"]),
        "orb": _finite_number(value["orb"]),
        "orb_limit": _finite_number(value["orb_limit"]),
        "applying": value.get("applying"),
    }
    if result["applying"] not in {True, False, None}:
        raise SkyChatValidationError("aspect applying state is invalid")
    summary = value.get("seed_summary")
    if isinstance(summary, str) and summary.strip():
        result["seed_summary"] = _truncate(summary.strip(), 500)
    return result


def _ready_sign_summary(store: InterpretationLookup | None, sign: str) -> str:
    if store is None:
        return ""
    try:
        entry = store.get(f"sign:{sign}")
    except (KeyError, TypeError, ValueError):
        return ""
    if entry is None or entry.status != "ready":
        return ""
    return _truncate(entry.summary.strip(), 500) if entry.summary.strip() else ""


def _placements_for_ids(
    lookup: Mapping[str, Mapping[str, Any]],
    ids: Sequence[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for identity in ids:
        if identity in seen or identity not in lookup:
            continue
        seen.add(identity)
        result.append(dict(lookup[identity]))
        if len(result) >= limit:
            break
    return result


def _mapping_items(
    value: Mapping[str, Any],
    parent: str,
    child: str,
) -> tuple[Mapping[str, Any], ...]:
    container = value.get(parent)
    if not isinstance(container, Mapping):
        raise SkyChatValidationError(f"facts.{parent} must be an object")
    return _list_items(container.get(child))


def _list_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise SkyChatValidationError("Sky Chat fact collection must be an array of objects")
    return tuple(value)


def _selector(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkyChatValidationError(f"{name} must be a non-empty string")
    return re.sub(r"[ -]+", "_", value.strip().casefold())


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise SkyChatValidationError("Sky Chat facts must contain finite numbers")
    result = float(value)
    if not math.isfinite(result):
        raise SkyChatValidationError("Sky Chat facts must contain finite numbers")
    return round(result, 6)


def _turns_json(turns: tuple[SkyChatTurn, ...]) -> str:
    return json.dumps(
        [turn.to_storage_dict() for turn in turns],
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _thread_key(
    user_id: str,
    cache_date: str,
    fingerprint: str,
) -> tuple[str, str, str]:
    normalized = normalize_user_id(user_id)
    if normalized != user_id:
        raise ValueError("user_id must already be normalized")
    canonical_date = _canonical_cache_date(cache_date)
    if not isinstance(fingerprint, str) or _FINGERPRINT_RE.fullmatch(fingerprint) is None:
        raise ValueError("natal_fingerprint must be a lowercase SHA-256 digest")
    return normalized, canonical_date, fingerprint


def _canonical_cache_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("cache_date must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("cache_date must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError("cache_date must be a canonical ISO date")
    return value


def _canonical_token(value: Any, name: str) -> str:
    if not isinstance(value, str) or _TOKEN_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe identifier")
    return value


def _validate_client_thread_id(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise SkyChatValidationError("thread_id must be a non-empty string of at most 128 characters")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise SkyChatValidationError("thread_id contains unsupported control characters")


def _new_id() -> str:
    return uuid4().hex


def _aware_utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _utc_isoformat(value: datetime) -> str:
    return _aware_utc(value, "timestamp").isoformat()


def _truncate(value: str, maximum: int) -> str:
    if len(value) <= maximum:
        return value
    return value[: maximum - 1].rstrip() + "…"


__all__ = [
    "DeepSeekSkyChatAuthor",
    "GeneratedSkyChatReply",
    "MemorySkyChatStore",
    "SKY_CHAT_EPISTEMIC",
    "SKY_CHAT_FACTS_TYPE",
    "SKY_CHAT_FULL_ASPECT_CAP",
    "SKY_CHAT_MAX_HISTORY_TURNS",
    "SKY_CHAT_MAX_MESSAGE_CHARS",
    "SKY_CHAT_MAX_REPLIES_PER_DAY",
    "SKY_CHAT_SCHEMA_VERSION",
    "SKY_CHAT_SYSTEM_PROMPT",
    "SKY_CHAT_TYPE",
    "SQLiteSkyChatStore",
    "SkyChatAuthor",
    "SkyChatError",
    "SkyChatFocus",
    "SkyChatPendingError",
    "SkyChatRateLimitError",
    "SkyChatService",
    "SkyChatStore",
    "SkyChatStoreError",
    "SkyChatThread",
    "SkyChatTurn",
    "SkyChatValidationError",
    "build_sky_chat_facts",
    "normalize_sky_chat_focus",
    "sky_chat_service_from_env",
    "validate_sky_chat_message",
    "validate_sky_chat_reply",
]
