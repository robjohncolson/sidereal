"""Interpretation record schema and deterministic v1 inventory.

The calculation engine deliberately does not import this module.  This layer
owns symbolic text keys and their validation, keeping interpretation separate
from astronomical geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import combinations
import re
from typing import Any, Iterable, Mapping


SIGNS: tuple[str, ...] = (
    "aries",
    "taurus",
    "gemini",
    "cancer",
    "leo",
    "virgo",
    "libra",
    "scorpio",
    "ophiuchus",
    "sagittarius",
    "capricorn",
    "aquarius",
    "pisces",
)

PLANETS: tuple[str, ...] = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
    "north_node",
    "south_node",
)

# Normative CODEX_PROMPT v1 set. South Node, Descendant, and IC are displayed
# geometrically but intentionally do not receive v1 aspect interpretation keys.
ASPECT_BODIES: tuple[str, ...] = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
    "north_node",
    "asc",
    "mc",
)

ASPECT_TYPES: tuple[str, ...] = (
    "conjunction",
    "opposition",
    "trine",
    "square",
    "sextile",
)
ANGLES: tuple[str, ...] = ("asc", "mc")
PATTERN_TYPES: tuple[str, ...] = ("stellium", "t_square", "grand_trine")

ENTRY_TYPES: tuple[str, ...] = (
    "sign",
    "house",
    "planet",
    "planet_in_sign",
    "planet_in_house",
    "sign_on_house",
    "aspect",
    "pattern",
    "angle_in_sign",
)
STATUSES: tuple[str, ...] = ("stub", "ready", "user")
SOURCES: tuple[str, ...] = ("original", "user", "generated_draft")

SEED_DATE = "2026-07-10"
SCHEMA_VERSION = 1
CORE_INVENTORY_COUNT = 909
TOTAL_INVENTORY_COUNT = 912  # Normative core plus all implemented pattern keys.
SEED1_READY_COUNT = 76
# Personal-planet major aspects: C(7, 2) pairs × 5 aspect types.
SEED2_PERSONAL_PLANETS: tuple[str, ...] = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
)
SEED2_READY_COUNT = 105
# Phase 3 keeps the same practical personal-planet scope for house readings.
# The remaining outer-planet and node house records stay visible as inventory
# stubs until a later content pass can give them comparable editorial care.
SEED3_PERSONAL_PLANETS: tuple[str, ...] = SEED2_PERSONAL_PLANETS
# 7 planets x 12 houses + 13 signs x 12 houses + 13 MC signs + 3 patterns.
SEED3_READY_COUNT = 256
# Phase 4 completes the sign readings for the three personal planets whose
# house readings shipped in Seed 3, then upgrades every remaining outer-planet
# and lunar-node house stub.
SEED4_SIGN_PLANETS: tuple[str, ...] = ("mercury", "venus", "mars")
SEED4_HOUSE_BODIES: tuple[str, ...] = (
    "uranus",
    "neptune",
    "pluto",
    "north_node",
    "south_node",
)
# 3 planets x 13 signs + 5 bodies/points x 12 houses.
SEED4_READY_COUNT = 99
# Phase 4 relationship readings pair the same seven personal bodies used by
# Seed 2 with four outer/node counterparts and the two chart angles.  The
# resulting ids remain canonical unordered aspect ids in the Seed 0 inventory.
SEED5_PERSONAL_BODIES: tuple[str, ...] = SEED2_PERSONAL_PLANETS
SEED5_OUTER_NODE_BODIES: tuple[str, ...] = (
    "uranus",
    "neptune",
    "pluto",
    "north_node",
)
SEED5_ANGLES: tuple[str, ...] = ANGLES
# 7 personal bodies x (4 outer/node bodies + 2 angles) x 5 major aspects.
SEED5_READY_COUNT = 210
# Seed 7 completes Midpoint sign character for every remaining planet/node so
# aspect composition can always attach zodiac-colored placement notes.
SEED7_SIGN_BODIES: tuple[str, ...] = (
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
    "north_node",
    "south_node",
)
# 7 bodies x 13 signs.
SEED7_READY_COUNT = 91

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")


DISPLAY_NAMES: dict[str, str] = {
    **{sign: sign.title() for sign in SIGNS},
    **{planet: planet.replace("_", " ").title() for planet in PLANETS},
    "asc": "Ascendant",
    "mc": "Midheaven",
    "stellium": "Stellium",
    "t_square": "T-Square",
    "grand_trine": "Grand Trine",
}


@dataclass(frozen=True, slots=True)
class InterpretationEntry:
    """One validated interpretation database record."""

    id: str
    type: str
    title: str
    keywords: tuple[str, ...]
    summary: str
    planet: str | None = None
    sign: str | None = None
    house: int | None = None
    angle: str | None = None
    body_a: str | None = None
    body_b: str | None = None
    aspect_type: str | None = None
    pattern_type: str | None = None
    body: str = ""
    shadow: str = ""
    growth: str = ""
    blend_note: str = ""
    source: str = "generated_draft"
    license: str = "personal-use"
    status: str = "stub"
    version: int = 1
    updated: str = SEED_DATE

    def __post_init__(self) -> None:
        validate_entry(self)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "keywords": list(self.keywords),
            "summary": self.summary,
            "source": self.source,
            "license": self.license,
            "status": self.status,
            "version": self.version,
            "updated": self.updated,
        }
        for name in (
            "planet",
            "sign",
            "house",
            "angle",
            "body_a",
            "body_b",
            "aspect_type",
            "pattern_type",
        ):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        for name in ("body", "shadow", "growth", "blend_note"):
            value = getattr(self, name)
            if value:
                result[name] = value
        return result

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "InterpretationEntry":
        allowed = {
            "id",
            "type",
            "title",
            "keywords",
            "summary",
            "planet",
            "sign",
            "house",
            "angle",
            "body_a",
            "body_b",
            "aspect_type",
            "pattern_type",
            "body",
            "shadow",
            "growth",
            "blend_note",
            "source",
            "license",
            "status",
            "version",
            "updated",
        }
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown interpretation fields: {sorted(unknown)}")
        keywords = raw.get("keywords")
        if not isinstance(keywords, (list, tuple)):
            raise ValueError("keywords must be an array")
        values = dict(raw)
        values["keywords"] = tuple(keywords)
        return cls(**values)  # type: ignore[arg-type]


def _require_slug(value: str, label: str) -> None:
    if not _SLUG_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase identifier: {value!r}")


def _canonical_entry_id(entry: InterpretationEntry) -> str:
    if entry.type == "sign":
        if entry.sign not in SIGNS:
            raise ValueError(f"invalid sign: {entry.sign!r}")
        return f"sign:{entry.sign}"
    if entry.type == "house":
        if not _is_house_number(entry.house):
            raise ValueError(f"invalid house: {entry.house!r}")
        return f"house:{entry.house}"
    if entry.type == "planet":
        if entry.planet not in PLANETS:
            raise ValueError(f"invalid planet: {entry.planet!r}")
        return f"planet:{entry.planet}"
    if entry.type == "planet_in_sign":
        if entry.planet not in PLANETS or entry.sign not in SIGNS:
            raise ValueError("invalid planet_in_sign selectors")
        return f"planet_in_sign:{entry.planet}:{entry.sign}"
    if entry.type == "planet_in_house":
        if entry.planet not in PLANETS or not _is_house_number(entry.house):
            raise ValueError("invalid planet_in_house selectors")
        return f"planet_in_house:{entry.planet}:{entry.house}"
    if entry.type == "sign_on_house":
        if entry.sign not in SIGNS or not _is_house_number(entry.house):
            raise ValueError("invalid sign_on_house selectors")
        return f"sign_on_house:{entry.sign}:{entry.house}"
    if entry.type == "angle_in_sign":
        if entry.angle not in ANGLES or entry.sign not in SIGNS:
            raise ValueError("invalid angle_in_sign selectors")
        return f"angle_in_sign:{entry.angle}:{entry.sign}"
    if entry.type == "aspect":
        if entry.body_a not in ASPECT_BODIES or entry.body_b not in ASPECT_BODIES:
            raise ValueError("invalid aspect bodies")
        if entry.body_a >= entry.body_b:
            raise ValueError("aspect bodies must be distinct and alphabetically sorted")
        if entry.aspect_type not in ASPECT_TYPES:
            raise ValueError(f"invalid v1 aspect type: {entry.aspect_type!r}")
        return f"aspect:{entry.body_a}:{entry.aspect_type}:{entry.body_b}"
    if entry.type == "pattern":
        if not isinstance(entry.pattern_type, str) or not entry.pattern_type:
            raise ValueError("pattern_type is required")
        _require_slug(entry.pattern_type, "pattern_type")
        return f"pattern:{entry.pattern_type}"
    raise ValueError(f"invalid interpretation type: {entry.type!r}")


def validate_entry(entry: InterpretationEntry) -> None:
    for field_name in (
        "id", "type", "title", "summary", "source", "license", "status", "updated",
        "body", "shadow", "growth", "blend_note",
    ):
        if not isinstance(getattr(entry, field_name), str):
            raise ValueError(f"{field_name} must be a string")
    if entry.type not in ENTRY_TYPES:
        raise ValueError(f"invalid interpretation type: {entry.type!r}")
    if not entry.title.strip():
        raise ValueError("title must not be blank")
    if not entry.summary.strip():
        raise ValueError("summary must not be blank")
    if not entry.license.strip():
        raise ValueError("license must not be blank")
    if not entry.keywords or any(not isinstance(k, str) or not k.strip() for k in entry.keywords):
        raise ValueError("keywords must contain non-blank strings")
    if entry.status not in STATUSES:
        raise ValueError(f"invalid status: {entry.status!r}")
    if entry.source not in SOURCES:
        raise ValueError(f"invalid source: {entry.source!r}")
    if not isinstance(entry.version, int) or isinstance(entry.version, bool) or entry.version < 1:
        raise ValueError("version must be a positive integer")
    try:
        date.fromisoformat(entry.updated)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"updated must be an ISO date: {entry.updated!r}") from exc
    canonical = _canonical_entry_id(entry)
    if entry.id != canonical:
        raise ValueError(f"non-canonical id {entry.id!r}; expected {canonical!r}")


def _is_house_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 12


def aspect_key(body_a: str, aspect_type: str, body_b: str) -> str:
    """Return the unordered, alphabetically canonical v1 aspect key."""

    a, b = sorted((body_a, body_b))
    if a == b:
        raise ValueError("an aspect interpretation requires two distinct bodies")
    if a not in ASPECT_BODIES or b not in ASPECT_BODIES:
        raise ValueError(f"unsupported v1 aspect bodies: {a!r}, {b!r}")
    if aspect_type not in ASPECT_TYPES:
        raise ValueError(f"unsupported v1 aspect type: {aspect_type!r}")
    return f"aspect:{a}:{aspect_type}:{b}"


# Each theme has original, compact language used by Seed 1 and component
# keywords used to make the remaining stubs useful without pretending they are
# finished interpretations.
SIGN_CONTENT: dict[str, dict[str, Any]] = {
    "aries": {
        "keywords": ("initiative", "directness", "courage"),
        "summary": "Aries is symbolically associated with initiation, direct action, and the courage to meet a situation plainly. Its working tension is between decisive movement and enough pause to choose a useful direction.",
        "expression": "initiative, candor, and a willingness to begin",
        "invitation": "pair swift self-direction with awareness of consequences",
    },
    "taurus": {
        "keywords": ("stability", "sensation", "stewardship"),
        "summary": "Taurus is traditionally associated with steadiness, sensory presence, and careful stewardship of what has value. Its symbolism asks how persistence can provide continuity without becoming resistance to necessary change.",
        "expression": "patience, embodied attention, and durable commitment",
        "invitation": "let stability support growth instead of closing change out",
    },
    "gemini": {
        "keywords": ("curiosity", "language", "connection"),
        "summary": "Gemini is associated with curiosity, language, comparison, and the movement of information between people. Its working tension is to stay adaptable while giving important questions enough sustained attention.",
        "expression": "curiosity, verbal agility, and connective thinking",
        "invitation": "turn many observations into clear and responsible understanding",
    },
    "cancer": {
        "keywords": ("belonging", "protection", "memory"),
        "summary": "Cancer is traditionally read through belonging, protection, memory, and sensitivity to emotional atmosphere. Its symbolism considers how care can create shelter while still allowing honest movement beyond familiar patterns.",
        "expression": "protective care, memory, and emotional attunement",
        "invitation": "build belonging without making familiarity the only measure of safety",
    },
    "leo": {
        "keywords": ("creativity", "warmth", "recognition"),
        "summary": "Leo is symbolically associated with creative presence, generosity, play, and the wish to be genuinely seen. Its working tension is to cultivate confident expression that also makes room for other people to shine.",
        "expression": "warmth, creative authorship, and visible conviction",
        "invitation": "offer what is distinctive without depending entirely on applause",
    },
    "virgo": {
        "keywords": ("discernment", "craft", "service"),
        "summary": "Virgo is associated with discernment, craft, practical service, and attention to the details that make a system work. Its symbolism asks for useful refinement while cautioning against treating every imperfection as a failure.",
        "expression": "careful observation, skill-building, and practical improvement",
        "invitation": "use discernment in service of wholeness rather than endless correction",
    },
    "libra": {
        "keywords": ("reciprocity", "balance", "perspective"),
        "summary": "Libra is traditionally associated with reciprocity, proportion, perspective, and the art of negotiating shared space. Its working tension is to seek fairness without losing contact with a clear personal position.",
        "expression": "diplomacy, aesthetic judgment, and relational awareness",
        "invitation": "make room for several perspectives while still choosing honestly",
    },
    "scorpio": {
        "keywords": ("depth", "trust", "transformation"),
        "summary": "Scorpio is symbolically associated with depth, trust, guarded resources, and change that exposes what is essential. Its symbolism asks for emotional honesty and responsible power rather than control for its own sake.",
        "expression": "intensity, perceptiveness, and commitment to what matters",
        "invitation": "use depth to clarify and transform rather than to harden suspicion",
    },
    "ophiuchus": {
        "keywords": ("integration", "liminality", "hard-won knowledge"),
        "summary": "Ophiuchus is treated here as a first-class sign associated with integration, liminal passages, and knowledge tested under pressure. Its symbolism concerns holding contradictions long enough to form a wiser response, not making medical or fated claims.",
        "expression": "boundary-crossing insight, integration, and composure under pressure",
        "invitation": "turn difficult knowledge into responsible and humane action",
    },
    "sagittarius": {
        "keywords": ("meaning", "exploration", "conviction"),
        "summary": "Sagittarius is associated with exploration, conviction, broad context, and the search for a meaningful orientation. Its working tension is to pursue a larger horizon while remaining answerable to evidence and lived detail.",
        "expression": "wide-ranging inquiry, candor, and a search for meaning",
        "invitation": "let experience refine conviction instead of using certainty to end inquiry",
    },
    "capricorn": {
        "keywords": ("responsibility", "structure", "mastery"),
        "summary": "Capricorn is traditionally associated with responsibility, structure, endurance, and mastery earned over time. Its symbolism asks how ambition and boundaries can support meaningful work without reducing worth to achievement.",
        "expression": "discipline, strategic patience, and respect for durable structure",
        "invitation": "build authority through responsibility while leaving room for human limits",
    },
    "aquarius": {
        "keywords": ("independence", "systems", "community"),
        "summary": "Aquarius is symbolically associated with independent thought, collective systems, experimentation, and future-facing questions. Its working tension is to contribute an original perspective without becoming detached from particular people and consequences.",
        "expression": "inventiveness, systems awareness, and principled independence",
        "invitation": "connect new ideas to the communities and realities they affect",
    },
    "pisces": {
        "keywords": ("imagination", "empathy", "permeability"),
        "summary": "Pisces is associated with imagination, empathy, permeability, and awareness of experiences that resist tidy categories. Its symbolism asks for compassion and creative openness together with boundaries that keep sensitivity workable.",
        "expression": "imagination, receptivity, and compassionate perception",
        "invitation": "give subtle impressions a grounded form and sustainable boundary",
    },
}


HOUSE_CONTENT: dict[int, dict[str, Any]] = {
    1: {"keywords": ("self-presentation", "approach", "beginnings"), "summary": "The first house is traditionally read as the arena of immediate self-presentation, embodied approach, and how one enters new situations. It describes a symbolic mode of engagement rather than a fixed identity."},
    2: {"keywords": ("resources", "values", "sufficiency"), "summary": "The second house is associated with resources, values, skills, and a working sense of sufficiency. Its symbolism asks what is cultivated, protected, and treated as worth sustaining."},
    3: {"keywords": ("learning", "communication", "local world"), "summary": "The third house is associated with everyday learning, communication, siblings or peers, and movement through the local environment. It highlights the habits through which information is gathered and exchanged."},
    4: {"keywords": ("roots", "home", "private foundation"), "summary": "The fourth house is traditionally read through home, roots, ancestry, and the private foundation beneath public life. Its symbolism concerns how belonging and inner continuity are made and revised."},
    5: {"keywords": ("creativity", "play", "self-expression"), "summary": "The fifth house is associated with creativity, play, romance, and forms of expression undertaken for their own vitality. It asks what a person chooses to bring forward and take joy in shaping."},
    6: {"keywords": ("routines", "craft", "maintenance"), "summary": "The sixth house is associated with routines, craft, service, and the maintenance that supports daily life. It symbolically emphasizes workable practices and the relationship between effort and function, without making health predictions."},
    7: {"keywords": ("partnership", "agreement", "encounter"), "summary": "The seventh house is traditionally associated with partnership, agreement, open conflict, and significant one-to-one encounters. Its symbolism explores how selfhood is negotiated in the presence of an equal other."},
    8: {"keywords": ("shared resources", "trust", "transition"), "summary": "The eighth house is associated with shared resources, trust, obligations, and transitions that require mutual accountability. It asks how entanglement, vulnerability, and consequential change are handled."},
    9: {"keywords": ("worldview", "study", "distance"), "summary": "The ninth house is traditionally read through worldview, advanced study, long journeys, and encounters with unfamiliar frameworks. Its symbolism concerns the search for orientation beyond the immediately known."},
    10: {"keywords": ("vocation", "reputation", "public responsibility"), "summary": "The tenth house is associated with vocation, reputation, public contribution, and visible responsibility. It describes the symbolic terrain of accountability and direction rather than guaranteeing status or career outcomes."},
    11: {"keywords": ("community", "alliance", "future aims"), "summary": "The eleventh house is associated with communities, alliances, audiences, and aims that extend beyond private concerns. Its symbolism asks how participation in a larger network shapes possibility and obligation."},
    12: {"keywords": ("retreat", "unseen patterns", "release"), "summary": "The twelfth house is traditionally read through retreat, solitude, unseen patterns, and forms of release or closure. It invites reflective attention to what operates outside ordinary visibility without treating mystery as diagnosis."},
}


# Seed 3 combines these authored arena descriptions with the existing planet
# and sign frames.  Keeping the axes separate makes every generated record
# deterministic while still giving each pairing content from both selectors.
HOUSE_FRAMES: dict[int, dict[str, str]] = {
    1: {
        "arena": "self-presentation, embodied approach, and the way beginnings are entered",
        "practice": "noticing how deliberate beginnings turn an inner principle into visible action",
    },
    2: {
        "arena": "resources, values, skills, and a workable sense of sufficiency",
        "practice": "cultivating resources in ways that reflect stated values rather than accumulation alone",
    },
    3: {
        "arena": "everyday learning, communication, peers, and movement through the local world",
        "practice": "asking clear questions and making everyday exchanges more accountable",
    },
    4: {
        "arena": "home, roots, memory, and the private foundation beneath public life",
        "practice": "building continuity that can be revised without treating familiarity as the only form of safety",
    },
    5: {
        "arena": "creativity, play, romance, and personally chosen forms of expression",
        "practice": "making room for play and authorship while tending the responsibilities that expression creates",
    },
    6: {
        "arena": "routines, craft, service, and the maintenance that supports daily life",
        "practice": "shaping sustainable routines without turning maintenance into self-judgment",
    },
    7: {
        "arena": "partnership, agreement, open disagreement, and significant one-to-one encounters",
        "practice": "stating needs and agreements directly while making room for an equal other",
    },
    8: {
        "arena": "shared resources, trust, obligations, and consequential transitions",
        "practice": "handling shared commitments with explicit consent, trust, and accountability",
    },
    9: {
        "arena": "worldview, sustained study, distance, and encounters with unfamiliar frameworks",
        "practice": "testing larger convictions against study, experience, and unfamiliar perspectives",
    },
    10: {
        "arena": "vocation, reputation, public contribution, and visible responsibility",
        "practice": "connecting visible responsibility with useful contribution rather than status alone",
    },
    11: {
        "arena": "community, alliance, audiences, and aims extending beyond private concerns",
        "practice": "participating in shared aims without giving away individual accountability",
    },
    12: {
        "arena": "retreat, solitude, unseen patterns, and processes of release or closure",
        "practice": "using reflection and retreat consciously while staying connected to ordinary life",
    },
}


PLANET_CONTENT: dict[str, dict[str, Any]] = {
    "sun": {"keywords": ("identity", "purpose", "vital expression"), "summary": "The Sun symbolizes coherent identity, purpose, and the wish to express a central organizing principle. It is traditionally read as a direction of conscious development, not proof of a fixed personality."},
    "moon": {"keywords": ("needs", "memory", "adaptation"), "summary": "The Moon symbolizes changing needs, memory, habit, and instinctive adaptation to an environment. Its placement is traditionally used to reflect on familiar emotional rhythms rather than to predict behavior."},
    "mercury": {"keywords": ("perception", "language", "reasoning"), "summary": "Mercury symbolizes perception, language, exchange, and the methods used to organize information. Its placement offers a working metaphor for how attention moves and meaning is communicated."},
    "venus": {"keywords": ("attraction", "values", "relating"), "summary": "Venus symbolizes attraction, values, pleasure, and the practices through which relationship and aesthetic preference are cultivated. It does not determine compatibility or financial outcomes."},
    "mars": {"keywords": ("agency", "desire", "assertion"), "summary": "Mars symbolizes agency, desire, conflict, and the capacity to act with force or precision. Its placement can frame reflection on assertion and effort without implying inevitable aggression."},
    "jupiter": {"keywords": ("expansion", "meaning", "confidence"), "summary": "Jupiter symbolizes expansion, confidence, teaching, and the search for a larger frame of meaning. Its traditional reading includes both generative opportunity and the need to notice excess."},
    "saturn": {"keywords": ("limits", "responsibility", "time"), "summary": "Saturn symbolizes limits, responsibility, time, and structures that are tested through sustained effort. It is best read as a language for boundaries and maturation, not punishment or doom."},
    "uranus": {"keywords": ("disruption", "independence", "innovation"), "summary": "Uranus symbolizes disruption, independence, experimentation, and breaks from an established pattern. Its placement can describe a field of symbolic revision without promising sudden events."},
    "neptune": {"keywords": ("imagination", "idealization", "dissolution"), "summary": "Neptune symbolizes imagination, idealization, ambiguity, and the loosening of ordinary boundaries. Its placement invites discernment between inspiration and projection without making clinical claims."},
    "pluto": {"keywords": ("power", "depth", "renewal"), "summary": "Pluto symbolizes power, depth, compulsion, and processes of symbolic breakdown and renewal. It is a reflective metaphor for consequential change, not a forecast of crisis."},
    "north_node": {"keywords": ("development", "stretch", "orientation"), "summary": "The North Node is traditionally treated as a symbolic orientation toward unfamiliar development and constructive stretch. It is a calculated point, not a planet or a command about destiny."},
    "south_node": {"keywords": ("familiarity", "inheritance", "release"), "summary": "The South Node is traditionally treated as a symbolic field of familiarity, inherited habits, and capacities already close at hand. It can be read as material to use consciously rather than a past that must be rejected."},
}


ASPECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "conjunction": ("concentration", "fusion"),
    "opposition": ("polarity", "negotiation"),
    "trine": ("flow", "reinforcement"),
    "square": ("friction", "development"),
    "sextile": ("cooperation", "opportunity"),
}

# Compact roles used only for Seed 2 aspect composition (personal planets).
PLANET_FOCUS: dict[str, str] = {
    "sun": "core purpose and self-definition",
    "moon": "emotional needs and habitual security",
    "mercury": "thinking, speech, and information habits",
    "venus": "values, attraction, and relating style",
    "mars": "drive, assertion, and how effort is applied",
    "jupiter": "expansion, confidence, and meaning-making",
    "saturn": "limits, responsibility, and long-term structure",
}


# Seed 5 preserves the five reusable aspect dynamics above while giving every
# endpoint its own authored focus and practical counterweight.  The two angle
# qualifications are deliberately geometry-conditional, and the North Node
# language keeps the calculated point distinct from a physical planet.
SEED5_PERSONAL_FRAMES: dict[str, dict[str, str]] = {
    "sun": {
        "focus": "core purpose, self-definition, and the wish to act from a coherent center",
        "practice": "Keep purpose flexible enough to answer evidence, circumstance, and other people's agency.",
    },
    "moon": {
        "focus": "emotional needs, memory, familiar rhythms, and instinctive adaptation",
        "practice": "Name the present need without assuming that the most familiar response is the only safe one.",
    },
    "mercury": {
        "focus": "attention, reasoning, language, and the exchange of information",
        "practice": "Make the reasoning process visible, check assumptions, and revise the message when new information arrives.",
    },
    "venus": {
        "focus": "values, attraction, pleasure, and the cultivation of reciprocal relationship",
        "practice": "State preferences without coercion and let consent, proportion, and reciprocity refine what is valued.",
    },
    "mars": {
        "focus": "agency, desire, assertion, and the way effort is directed",
        "practice": "Choose a proportionate action and distinguish a useful boundary from force applied by reflex.",
    },
    "jupiter": {
        "focus": "expansion, confidence, teaching, and the search for a larger frame of meaning",
        "practice": "Let experience enlarge the frame while checking confidence for overstatement, excess, or missing detail.",
    },
    "saturn": {
        "focus": "limits, responsibility, time, and structures tested through sustained effort",
        "practice": "Use boundaries to support accountable work without turning delay, difficulty, or limitation into a verdict of worth.",
    },
}


SEED5_COUNTERPART_FRAMES: dict[str, dict[str, str]] = {
    "uranus": {
        "focus": "independence, experimentation, and revision of an established pattern",
        "bridge": (
            "For this pairing, the question is how {personal_focus} can meet change "
            "without making novelty or reflexive disruption an end in itself."
        ),
        "practice": "Test experiments in workable increments and remain accountable to the people and systems they affect.",
        "qualification": "Uranus does not promise sudden events or require rebellion.",
    },
    "neptune": {
        "focus": "imagination, idealization, ambiguity, and the loosening of ordinary boundaries",
        "bridge": (
            "For this pairing, the question is how {personal_focus} can remain open to "
            "imagination while checking projection against evidence, consent, and practical limits."
        ),
        "practice": "Give subtle impressions a concrete form and keep inspiration answerable to observable reality.",
        "qualification": "Neptune does not diagnose confusion or guarantee inspiration.",
    },
    "pluto": {
        "focus": "power, depth, compulsion, and processes of symbolic breakdown and renewal",
        "bridge": (
            "For this pairing, the question is how {personal_focus} can encounter "
            "intensity and consequential change while preserving choice and accountability."
        ),
        "practice": "Name power dynamics plainly and favor forms of change that preserve agency rather than demanding control.",
        "qualification": "Pluto does not forecast crisis, loss, or inevitable transformation.",
    },
    "north_node": {
        "focus": "an unfamiliar direction of development, constructive stretch, and emerging orientation",
        "bridge": (
            "For this pairing, the question is how {personal_focus} can test unfamiliar "
            "capacities without mistaking novelty, discomfort, or symbolism for an instruction."
        ),
        "practice": "Approach unfamiliar capacities through small experiments and evaluate what they actually make possible.",
        "qualification": "The North Node is a calculated point, not a planet or a destiny signal.",
    },
    "asc": {
        "focus": "observable approach, embodied entry into situations, and self-presentation",
        "bridge": (
            "For this pairing, the question is how that personal focus becomes legible in "
            "first responses without reducing the whole person to an outward manner."
        ),
        "practice": "Notice how an inner theme enters visible behavior, then compare the first response with the fuller context.",
        "qualification": "This reading applies only when known birth-time geometry supplies the Ascendant; it is not a fixed identity.",
    },
    "mc": {
        "focus": "public direction, visible contribution, and accountability within a role",
        "bridge": (
            "For this pairing, the question is how {personal_focus} can participate in "
            "visible responsibility without equating public response with personal worth."
        ),
        "practice": "Connect visible choices to useful contribution and revise the role when circumstances or responsibilities change.",
        "qualification": "This reading applies only when known birth-time geometry supplies the Midheaven; it does not promise a career outcome.",
    },
}


# Authored Seed 4 axes.  Pairing these compact body frames with the distinct
# sign and house frames keeps generation deterministic without flattening
# Ophiuchus or treating the calculated lunar nodes as planets.
SEED4_SIGN_FRAMES: dict[str, dict[str, str]] = {
    "mercury": {
        "focus": "attention, language, exchange, and the methods used to organize information",
        "practice": "make the reasoning process visible, test assumptions, and adapt the message to its actual audience",
    },
    "venus": {
        "focus": "values, attraction, pleasure, and the practices through which relationship is cultivated",
        "practice": "name what is valued, communicate preferences without coercion, and let reciprocity refine taste",
    },
    "mars": {
        "focus": "agency, desire, conflict, and the way effort is directed",
        "practice": "choose a proportionate action, state boundaries clearly, and distinguish purposeful effort from reflexive force",
    },
}

# Sign-character frames for bodies still stubbed after Seeds 1 and 4.
SEED7_SIGN_FRAMES: dict[str, dict[str, str]] = {
    "jupiter": {
        "focus": "expansion, confidence, teaching, and the search for a larger frame of meaning",
        "practice": "test broad convictions against lived detail and share perspective without overselling certainty",
    },
    "saturn": {
        "focus": "limits, responsibility, time, and structures tested through sustained effort",
        "practice": "build durable boundaries, honor real constraints, and revise ambition when capacity is finite",
    },
    "uranus": {
        "focus": "independence, experimentation, and revision of an established pattern",
        "practice": "introduce change in accountable increments and keep unusual insight answerable to consequences",
    },
    "neptune": {
        "focus": "imagination, idealization, ambiguity, and sensitivity to porous boundaries",
        "practice": "give subtle impressions a workable form while checking projection against evidence and consent",
    },
    "pluto": {
        "focus": "power, depth, compulsion, and processes of symbolic renewal",
        "practice": "name power dynamics plainly and choose forms of intensity that preserve agency",
    },
    "north_node": {
        "focus": "unfamiliar development, constructive stretch, and emerging orientation",
        "practice": "approach stretch goals through small experiments rather than treating discomfort as destiny",
    },
    "south_node": {
        "focus": "familiar capacities, inherited habits, and material already close at hand",
        "practice": "use familiar strengths consciously while releasing habits that no longer serve the situation",
    },
}


SEED4_HOUSE_FRAMES: dict[str, dict[str, str]] = {
    "uranus": {
        "focus": "independence, experimentation, and revision of an established pattern",
        "qualification": "Uranus does not promise disruption or sudden events",
        "practice": "test changes in workable increments and remain accountable to the people and systems they affect",
    },
    "neptune": {
        "focus": "imagination, idealization, ambiguity, and sensitivity to porous boundaries",
        "qualification": "Neptune does not diagnose confusion or guarantee inspiration",
        "practice": "give imagination a concrete form while checking projections against evidence and consent",
    },
    "pluto": {
        "focus": "power, depth, compulsion, and processes of symbolic renewal",
        "qualification": "Pluto does not forecast crisis, loss, or inevitable transformation",
        "practice": "notice power dynamics plainly and choose forms of change that preserve agency and accountability",
    },
    "north_node": {
        "focus": "an unfamiliar direction of development, constructive stretch, and emerging orientation",
        "qualification": "The North Node is a calculated point, not a planet or a command about destiny",
        "practice": "approach unfamiliar capacities through small experiments rather than treating discomfort as an instruction",
    },
    "south_node": {
        "focus": "familiar capacities, inherited habits, and material already close at hand",
        "qualification": "The South Node is a calculated point, not a planet or proof of a predetermined past",
        "practice": "use familiar strengths consciously while releasing habits that no longer serve the situation",
    },
}

ASPECT_FRAMES: dict[str, dict[str, str]] = {
    "conjunction": {
        "relation": "fuse into a single point of emphasis",
        "detail": (
            "The two themes may feel hard to separate, so conscious sequencing and "
            "proportion matter more than treating either as optional."
        ),
        "growth": "Name which theme is leading in a given situation so fusion does not become confusion.",
    },
    "opposition": {
        "relation": "stand in a polarity that asks for negotiation",
        "detail": (
            "Each side can illuminate the other; growth often comes from alternating attention "
            "rather than declaring one pole correct."
        ),
        "growth": "Practice stating both needs plainly before choosing a temporary priority.",
    },
    "trine": {
        "relation": "support each other with relative ease",
        "detail": (
            "The connection can feel natural and therefore easy to underuse; the opportunity "
            "is deliberate cultivation rather than complacency."
        ),
        "growth": "Put the easy rapport to work on a concrete aim so talent becomes practice.",
    },
    "square": {
        "relation": "meet through productive friction",
        "detail": (
            "Tension is traditionally read as a developmental engine: the friction names a "
            "skill that must be built, not a verdict of failure."
        ),
        "growth": "Translate irritation into a specific skill or boundary to train.",
    },
    "sextile": {
        "relation": "offer cooperative opportunity when activated",
        "detail": (
            "The link is available rather than automatic; modest, repeated effort often "
            "unlocks more than waiting for inspiration."
        ),
        "growth": "Choose one small joint practice that makes the opportunity habitual.",
    },
}

ANGLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "asc": ("approach", "self-presentation"),
    "mc": ("public direction", "vocation"),
}


PATTERN_CONTENT: dict[str, dict[str, Any]] = {
    "stellium": {
        "keywords": ("concentration", "emphasis", "coordination"),
        "summary": (
            "A stellium is a structural concentration of three or more chart points in one "
            "sign. Symbolically, it marks repeated emphasis whose different functions may "
            "need coordination; it does not guarantee that one theme controls a life."
        ),
        "growth": "Name the separate roles inside the concentration instead of treating them as one undifferentiated force.",
    },
    "t_square": {
        "keywords": ("polarity", "friction", "apex"),
        "summary": (
            "A T-square is a structural pattern in which two opposing chart points each form "
            "a square to a third, or apex, point. Its symbolism emphasizes a recurring field "
            "of negotiation and action, not an inescapable conflict or forecast."
        ),
        "growth": "Use the apex as a place to practice a specific response while continuing to hear both ends of the polarity.",
    },
    "grand_trine": {
        "keywords": ("flow", "reinforcement", "circulation"),
        "summary": (
            "A grand trine is a structural circuit of three chart points joined pairwise by "
            "trines. It is traditionally read as mutually reinforcing flow that becomes most "
            "useful through deliberate practice, not as proof of effortless talent or luck."
        ),
        "growth": "Give the easy circulation a concrete task so familiarity develops into a practiced capacity.",
    },
}


def _display(identifier: str) -> str:
    return DISPLAY_NAMES.get(identifier, identifier.replace("_", " ").title())


def _stub_summary(title: str) -> str:
    return f"A fuller symbolic reading for {title} is not yet authored; use these keywords only as working notes."


def _stub_entry(
    *,
    entry_id: str,
    entry_type: str,
    title: str,
    keywords: Iterable[str],
    **selectors: Any,
) -> InterpretationEntry:
    return InterpretationEntry(
        id=entry_id,
        type=entry_type,
        title=title,
        keywords=tuple(dict.fromkeys(keywords)),
        summary=_stub_summary(title),
        source="generated_draft",
        status="stub",
        version=1,
        updated=SEED_DATE,
        **selectors,
    )


def generate_seed0_entries() -> tuple[InterpretationEntry, ...]:
    """Generate every supported v1 key as a useful but explicit stub."""

    records: list[InterpretationEntry] = []
    for sign in SIGNS:
        records.append(
            _stub_entry(
                entry_id=f"sign:{sign}",
                entry_type="sign",
                title=_display(sign),
                keywords=SIGN_CONTENT[sign]["keywords"],
                sign=sign,
            )
        )
    for house in range(1, 13):
        records.append(
            _stub_entry(
                entry_id=f"house:{house}",
                entry_type="house",
                title=f"House {house}",
                keywords=HOUSE_CONTENT[house]["keywords"],
                house=house,
            )
        )
    for planet in PLANETS:
        records.append(
            _stub_entry(
                entry_id=f"planet:{planet}",
                entry_type="planet",
                title=_display(planet),
                keywords=PLANET_CONTENT[planet]["keywords"],
                planet=planet,
            )
        )
    for planet in PLANETS:
        for sign in SIGNS:
            title = f"{_display(planet)} in {_display(sign)}"
            records.append(
                _stub_entry(
                    entry_id=f"planet_in_sign:{planet}:{sign}",
                    entry_type="planet_in_sign",
                    title=title,
                    keywords=PLANET_CONTENT[planet]["keywords"][:2] + SIGN_CONTENT[sign]["keywords"][:2],
                    planet=planet,
                    sign=sign,
                )
            )
    for planet in PLANETS:
        for house in range(1, 13):
            title = f"{_display(planet)} in House {house}"
            records.append(
                _stub_entry(
                    entry_id=f"planet_in_house:{planet}:{house}",
                    entry_type="planet_in_house",
                    title=title,
                    keywords=PLANET_CONTENT[planet]["keywords"][:2] + HOUSE_CONTENT[house]["keywords"][:2],
                    planet=planet,
                    house=house,
                )
            )
    for sign in SIGNS:
        for house in range(1, 13):
            title = f"{_display(sign)} on House {house}"
            records.append(
                _stub_entry(
                    entry_id=f"sign_on_house:{sign}:{house}",
                    entry_type="sign_on_house",
                    title=title,
                    keywords=SIGN_CONTENT[sign]["keywords"][:2] + HOUSE_CONTENT[house]["keywords"][:2],
                    sign=sign,
                    house=house,
                )
            )
    for body_a, body_b in combinations(sorted(ASPECT_BODIES), 2):
        for aspect_type in ASPECT_TYPES:
            title = f"{_display(body_a)} {aspect_type.title()} {_display(body_b)}"
            body_a_keywords = (
                PLANET_CONTENT[body_a]["keywords"][:1]
                if body_a in PLANET_CONTENT
                else ANGLE_KEYWORDS[body_a][:1]
            )
            body_b_keywords = (
                PLANET_CONTENT[body_b]["keywords"][:1]
                if body_b in PLANET_CONTENT
                else ANGLE_KEYWORDS[body_b][:1]
            )
            records.append(
                _stub_entry(
                    entry_id=f"aspect:{body_a}:{aspect_type}:{body_b}",
                    entry_type="aspect",
                    title=title,
                    keywords=body_a_keywords + ASPECT_KEYWORDS[aspect_type] + body_b_keywords,
                    body_a=body_a,
                    body_b=body_b,
                    aspect_type=aspect_type,
                )
            )
    for angle in ANGLES:
        for sign in SIGNS:
            title = f"{_display(angle)} in {_display(sign)}"
            records.append(
                _stub_entry(
                    entry_id=f"angle_in_sign:{angle}:{sign}",
                    entry_type="angle_in_sign",
                    title=title,
                    keywords=ANGLE_KEYWORDS[angle] + SIGN_CONTENT[sign]["keywords"][:2],
                    angle=angle,
                    sign=sign,
                )
            )
    pattern_keywords = {
        "stellium": ("concentration", "emphasis", "coordination"),
        "t_square": ("tension", "release point", "development"),
        "grand_trine": ("flow", "reinforcement", "integration"),
    }
    for pattern_type in PATTERN_TYPES:
        records.append(
            _stub_entry(
                entry_id=f"pattern:{pattern_type}",
                entry_type="pattern",
                title=_display(pattern_type),
                keywords=pattern_keywords[pattern_type],
                pattern_type=pattern_type,
            )
        )
    if len(records) != TOTAL_INVENTORY_COUNT:
        raise AssertionError(f"inventory bug: expected {TOTAL_INVENTORY_COUNT}, generated {len(records)}")
    if len({entry.id for entry in records}) != len(records):
        raise AssertionError("inventory generator produced duplicate ids")
    return tuple(records)


def _ready_entry(
    *,
    entry_id: str,
    entry_type: str,
    title: str,
    keywords: Iterable[str],
    summary: str,
    growth: str = "",
    **selectors: Any,
) -> InterpretationEntry:
    return InterpretationEntry(
        id=entry_id,
        type=entry_type,
        title=title,
        keywords=tuple(dict.fromkeys(keywords)),
        summary=summary,
        growth=growth,
        source="original",
        status="ready",
        version=2,
        updated=SEED_DATE,
        **selectors,
    )


def generate_seed1_entries() -> tuple[InterpretationEntry, ...]:
    """Generate the exact 76 original, non-stub Seed 1 records."""

    records: list[InterpretationEntry] = []
    for sign in SIGNS:
        content = SIGN_CONTENT[sign]
        records.append(
            _ready_entry(
                entry_id=f"sign:{sign}",
                entry_type="sign",
                title=_display(sign),
                keywords=content["keywords"],
                summary=content["summary"],
                sign=sign,
            )
        )
    for house in range(1, 13):
        content = HOUSE_CONTENT[house]
        records.append(
            _ready_entry(
                entry_id=f"house:{house}",
                entry_type="house",
                title=f"House {house}",
                keywords=content["keywords"],
                summary=content["summary"],
                house=house,
            )
        )
    for planet in PLANETS:
        content = PLANET_CONTENT[planet]
        records.append(
            _ready_entry(
                entry_id=f"planet:{planet}",
                entry_type="planet",
                title=_display(planet),
                keywords=content["keywords"],
                summary=content["summary"],
                planet=planet,
            )
        )
    for planet in ("sun", "moon"):
        for sign in SIGNS:
            sign_content = SIGN_CONTENT[sign]
            if planet == "sun":
                summary = (
                    f"Sun in {_display(sign)} is traditionally read as identity and purpose expressed through "
                    f"{sign_content['expression']}. This placement may invite a person to "
                    f"{sign_content['invitation']}; it does not define personality or fate."
                )
            else:
                summary = (
                    f"Moon in {_display(sign)} symbolically links changing needs, memory, and habit with "
                    f"{sign_content['expression']}. A useful working question is how this style can "
                    f"respect genuine emotional limits and {sign_content['invitation']}."
                )
            records.append(
                _ready_entry(
                    entry_id=f"planet_in_sign:{planet}:{sign}",
                    entry_type="planet_in_sign",
                    title=f"{_display(planet)} in {_display(sign)}",
                    keywords=PLANET_CONTENT[planet]["keywords"][:2] + sign_content["keywords"],
                    summary=summary,
                    blend_note="When near a boundary, read this alongside the adjacent sign as two symbolic lenses rather than a fractional identity.",
                    planet=planet,
                    sign=sign,
                )
            )
    for sign in SIGNS:
        sign_content = SIGN_CONTENT[sign]
        summary = (
            f"{_display(sign)} on the Ascendant is traditionally read as an immediate approach shaped by "
            f"{sign_content['expression']}. It may invite the outward style to "
            f"{sign_content['invitation']}, without reducing the person to a first impression."
        )
        records.append(
            _ready_entry(
                entry_id=f"angle_in_sign:asc:{sign}",
                entry_type="angle_in_sign",
                title=f"Ascendant in {_display(sign)}",
                keywords=ANGLE_KEYWORDS["asc"] + sign_content["keywords"],
                summary=summary,
                blend_note="Near a sign boundary, include the adjacent Ascendant reading and state the measured distance to the boundary.",
                angle="asc",
                sign=sign,
            )
        )
    if len(records) != SEED1_READY_COUNT:
        raise AssertionError(f"Seed 1 bug: expected {SEED1_READY_COUNT}, generated {len(records)}")
    if any(entry.status == "stub" for entry in records):
        raise AssertionError("Seed 1 must not contain stubs")
    return tuple(records)


def generate_seed2_entries() -> tuple[InterpretationEntry, ...]:
    """Generate ready major-aspect text for personal planets (Seed 2).

    Scope matches SPEC Seed 2: Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn
    across the five major aspect types. Body ids are stored alphabetically so keys
    match the unordered aspect inventory.
    """

    records: list[InterpretationEntry] = []
    for body_a, body_b in combinations(sorted(SEED2_PERSONAL_PLANETS), 2):
        focus_a = PLANET_FOCUS[body_a]
        focus_b = PLANET_FOCUS[body_b]
        for aspect_type in ASPECT_TYPES:
            frame = ASPECT_FRAMES[aspect_type]
            title = f"{_display(body_a)} {aspect_type.title()} {_display(body_b)}"
            summary = (
                f"{title} is traditionally read as a symbolic relationship in which "
                f"{focus_a} and {focus_b} {frame['relation']}. {frame['detail']} "
                f"This is a reflective lens for how those themes may interact, not a "
                f"prediction of character or outcomes."
            )
            records.append(
                _ready_entry(
                    entry_id=f"aspect:{body_a}:{aspect_type}:{body_b}",
                    entry_type="aspect",
                    title=title,
                    keywords=(
                        PLANET_CONTENT[body_a]["keywords"][:1]
                        + ASPECT_KEYWORDS[aspect_type]
                        + PLANET_CONTENT[body_b]["keywords"][:1]
                    ),
                    summary=summary,
                    growth=frame["growth"],
                    body_a=body_a,
                    body_b=body_b,
                    aspect_type=aspect_type,
                )
            )
    if len(records) != SEED2_READY_COUNT:
        raise AssertionError(f"Seed 2 bug: expected {SEED2_READY_COUNT}, generated {len(records)}")
    if any(entry.status == "stub" for entry in records):
        raise AssertionError("Seed 2 must not contain stubs")
    if len({entry.id for entry in records}) != len(records):
        raise AssertionError("Seed 2 generator produced duplicate ids")
    return tuple(records)


def generate_seed3_entries() -> tuple[InterpretationEntry, ...]:
    """Generate the required original placement and pattern readings for Seed 3."""

    records: list[InterpretationEntry] = []

    for planet in SEED3_PERSONAL_PLANETS:
        focus = PLANET_FOCUS[planet]
        for house in range(1, 13):
            house_frame = HOUSE_FRAMES[house]
            title = f"{_display(planet)} in House {house}"
            summary = (
                f"{title} symbolically brings {focus} into the arena of "
                f"{house_frame['arena']}. Houses are life-arena metaphors, not predictions; "
                "this pairing is a reflective prompt about where the planetary theme may "
                "receive attention, practice, or expression rather than a forecast of events."
            )
            records.append(
                _ready_entry(
                    entry_id=f"planet_in_house:{planet}:{house}",
                    entry_type="planet_in_house",
                    title=title,
                    keywords=(
                        PLANET_CONTENT[planet]["keywords"][:2]
                        + HOUSE_CONTENT[house]["keywords"]
                    ),
                    summary=summary,
                    growth=(
                        f"Practice {house_frame['practice']} while keeping {focus} in "
                        "proportion with the rest of the chart."
                    ),
                    planet=planet,
                    house=house,
                )
            )

    for sign in SIGNS:
        sign_content = SIGN_CONTENT[sign]
        for house in range(1, 13):
            house_frame = HOUSE_FRAMES[house]
            title = f"{_display(sign)} on House {house}"
            summary = (
                f"{title} is a symbolic cusp reading that colors {house_frame['arena']} "
                f"with {sign_content['expression']}. House cusps are life-arena metaphors "
                "rather than predictions; this pairing invites reflection on how that area "
                "may be approached, organized, and revised."
            )
            records.append(
                _ready_entry(
                    entry_id=f"sign_on_house:{sign}:{house}",
                    entry_type="sign_on_house",
                    title=title,
                    keywords=(
                        sign_content["keywords"] + HOUSE_CONTENT[house]["keywords"]
                    ),
                    summary=summary,
                    growth=(
                        f"Within this arena, {sign_content['invitation']}; also practice "
                        f"{house_frame['practice']}."
                    ),
                    sign=sign,
                    house=house,
                )
            )

    for sign in SIGNS:
        sign_content = SIGN_CONTENT[sign]
        title = f"Midheaven in {_display(sign)}"
        summary = (
            f"{_display(sign)} on the Midheaven is traditionally read as a public-direction "
            f"and vocation tone shaped by {sign_content['expression']}. It can describe a "
            f"style of visible contribution that seeks to {sign_content['invitation']}, "
            "while remaining a symbolic lens rather than a promise about career, status, "
            "or destiny."
        )
        records.append(
            _ready_entry(
                entry_id=f"angle_in_sign:mc:{sign}",
                entry_type="angle_in_sign",
                title=title,
                keywords=ANGLE_KEYWORDS["mc"] + sign_content["keywords"],
                summary=summary,
                growth=(
                    f"Ask how public choices can {sign_content['invitation']} while staying "
                    "answerable to real circumstances and other people."
                ),
                blend_note=(
                    "Near a sign boundary, include the adjacent Midheaven reading and state "
                    "the measured distance to the boundary."
                ),
                angle="mc",
                sign=sign,
            )
        )

    for pattern_type in PATTERN_TYPES:
        content = PATTERN_CONTENT[pattern_type]
        records.append(
            _ready_entry(
                entry_id=f"pattern:{pattern_type}",
                entry_type="pattern",
                title=_display(pattern_type),
                keywords=content["keywords"],
                summary=content["summary"],
                growth=content["growth"],
                pattern_type=pattern_type,
            )
        )

    if len(records) != SEED3_READY_COUNT:
        raise AssertionError(
            f"Seed 3 bug: expected {SEED3_READY_COUNT}, generated {len(records)}"
        )
    if any(entry.status != "ready" or entry.source != "original" for entry in records):
        raise AssertionError("Seed 3 must contain only original ready records")
    if any(entry.version <= 1 for entry in records):
        raise AssertionError("Seed 3 records must upgrade the v1 inventory stubs")
    if len({entry.id for entry in records}) != len(records):
        raise AssertionError("Seed 3 generator produced duplicate ids")
    return tuple(records)


def generate_seed4_entries() -> tuple[InterpretationEntry, ...]:
    """Generate the required original placement readings for Seed 4."""

    records: list[InterpretationEntry] = []

    for planet in SEED4_SIGN_PLANETS:
        planet_frame = SEED4_SIGN_FRAMES[planet]
        for sign in SIGNS:
            sign_content = SIGN_CONTENT[sign]
            title = f"{_display(planet)} in {_display(sign)}"
            summary = (
                f"{title} symbolically links {planet_frame['focus']} with "
                f"{sign_content['expression']}. This traditional placement is a reflective "
                "lens for how those themes may be expressed and revised, not a fixed "
                "personality description or a prediction of outcomes."
            )
            records.append(
                _ready_entry(
                    entry_id=f"planet_in_sign:{planet}:{sign}",
                    entry_type="planet_in_sign",
                    title=title,
                    keywords=(
                        PLANET_CONTENT[planet]["keywords"][:2]
                        + sign_content["keywords"]
                    ),
                    summary=summary,
                    growth=(
                        f"In this symbolic style, {sign_content['invitation']}; also "
                        f"{planet_frame['practice']}."
                    ),
                    blend_note=(
                        "When near a boundary, read this alongside the adjacent sign as "
                        "two symbolic lenses rather than a fractional identity."
                    ),
                    planet=planet,
                    sign=sign,
                )
            )

    for planet in SEED4_HOUSE_BODIES:
        planet_frame = SEED4_HOUSE_FRAMES[planet]
        for house in range(1, 13):
            house_frame = HOUSE_FRAMES[house]
            title = f"{_display(planet)} in House {house}"
            summary = (
                f"{title} symbolically locates {planet_frame['focus']} in the life arena "
                f"of {house_frame['arena']}. Houses are life-arena metaphors, not "
                f"predictions. {planet_frame['qualification']}. Read this pairing as a "
                "prompt for attention and choice rather than a forecast of events."
            )
            records.append(
                _ready_entry(
                    entry_id=f"planet_in_house:{planet}:{house}",
                    entry_type="planet_in_house",
                    title=title,
                    keywords=(
                        PLANET_CONTENT[planet]["keywords"][:2]
                        + HOUSE_CONTENT[house]["keywords"]
                    ),
                    summary=summary,
                    growth=(
                        f"Within this arena, {planet_frame['practice']}; also practice "
                        f"{house_frame['practice']}."
                    ),
                    planet=planet,
                    house=house,
                )
            )

    if len(records) != SEED4_READY_COUNT:
        raise AssertionError(
            f"Seed 4 bug: expected {SEED4_READY_COUNT}, generated {len(records)}"
        )
    if any(entry.status != "ready" or entry.source != "original" for entry in records):
        raise AssertionError("Seed 4 must contain only original ready records")
    if any(entry.version <= 1 for entry in records):
        raise AssertionError("Seed 4 records must upgrade the v1 inventory stubs")
    if any(len(entry.summary) < 100 for entry in records):
        raise AssertionError("Seed 4 summaries must be substantive")
    if len({entry.id for entry in records}) != len(records):
        raise AssertionError("Seed 4 generator produced duplicate ids")
    return tuple(records)


def generate_seed5_entries() -> tuple[InterpretationEntry, ...]:
    """Generate personal-to-outer/node and personal-to-angle major aspects."""

    records: list[InterpretationEntry] = []
    counterparts = SEED5_OUTER_NODE_BODIES + SEED5_ANGLES

    for personal in SEED5_PERSONAL_BODIES:
        personal_frame = SEED5_PERSONAL_FRAMES[personal]
        for counterpart in counterparts:
            counterpart_frame = SEED5_COUNTERPART_FRAMES[counterpart]
            body_a, body_b = sorted((personal, counterpart))
            counterpart_keywords = (
                PLANET_CONTENT[counterpart]["keywords"][:1]
                if counterpart in PLANET_CONTENT
                else ANGLE_KEYWORDS[counterpart][:1]
            )
            for aspect_type in ASPECT_TYPES:
                aspect_frame = ASPECT_FRAMES[aspect_type]
                title = f"{_display(body_a)} {aspect_type.title()} {_display(body_b)}"
                bridge = counterpart_frame["bridge"].rstrip(".")
                detail = aspect_frame["detail"]
                detail_after_semicolon = detail[0].lower() + detail[1:]
                qualification = counterpart_frame["qualification"].rstrip(".")
                summary = (
                    f"{title} is traditionally read as a symbolic relationship in which "
                    f"{personal_frame['focus']} and {counterpart_frame['focus']} "
                    f"{aspect_frame['relation']}. "
                    f"{bridge.format(personal_focus=personal_frame['focus'])}; "
                    f"{detail_after_semicolon} "
                    f"{qualification}; this is a symbolic study lens for themes that may "
                    "be observed and worked with, "
                    "not proof of character or a prediction of events or outcomes."
                )
                records.append(
                    _ready_entry(
                        entry_id=f"aspect:{body_a}:{aspect_type}:{body_b}",
                        entry_type="aspect",
                        title=title,
                        keywords=(
                            PLANET_CONTENT[personal]["keywords"][:1]
                            + ASPECT_KEYWORDS[aspect_type]
                            + counterpart_keywords
                        ),
                        summary=summary,
                        growth=(
                            f"{aspect_frame['growth']} {personal_frame['practice']} "
                            f"{counterpart_frame['practice']}"
                        ),
                        body_a=body_a,
                        body_b=body_b,
                        aspect_type=aspect_type,
                    )
                )

    if len(records) != SEED5_READY_COUNT:
        raise AssertionError(
            f"Seed 5 bug: expected {SEED5_READY_COUNT}, generated {len(records)}"
        )
    if any(entry.status != "ready" or entry.source != "original" for entry in records):
        raise AssertionError("Seed 5 must contain only original ready records")
    if any(entry.version <= 1 for entry in records):
        raise AssertionError("Seed 5 records must upgrade the v1 inventory stubs")
    if any(len(entry.summary) < 100 for entry in records):
        raise AssertionError("Seed 5 summaries must be substantive")
    if len({entry.id for entry in records}) != len(records):
        raise AssertionError("Seed 5 generator produced duplicate ids")
    return tuple(records)


def generate_seed7_entries() -> tuple[InterpretationEntry, ...]:
    """Complete planet/node × Midpoint-sign character for remaining bodies."""

    records: list[InterpretationEntry] = []
    for planet in SEED7_SIGN_BODIES:
        planet_frame = SEED7_SIGN_FRAMES[planet]
        for sign in SIGNS:
            sign_content = SIGN_CONTENT[sign]
            title = f"{_display(planet)} in {_display(sign)}"
            if planet in {"north_node", "south_node"}:
                summary = (
                    f"{title} symbolically pairs {planet_frame['focus']} with "
                    f"{sign_content['expression']}. {PLANET_CONTENT[planet]['summary']} "
                    f"In {_display(sign)}, the working invitation is to "
                    f"{sign_content['invitation']}. This is a reflective placement note, "
                    "not a command about fate or a fixed personality claim."
                )
            else:
                summary = (
                    f"{title} symbolically links {planet_frame['focus']} with "
                    f"{sign_content['expression']}. This Midpoint-sign placement is a "
                    "traditional lens for how that planetary theme may be colored, not a "
                    "fixed character verdict or a prediction of events."
                )
            records.append(
                _ready_entry(
                    entry_id=f"planet_in_sign:{planet}:{sign}",
                    entry_type="planet_in_sign",
                    title=title,
                    keywords=(
                        PLANET_CONTENT[planet]["keywords"][:2]
                        + sign_content["keywords"]
                    ),
                    summary=summary,
                    growth=(
                        f"In this symbolic style, {sign_content['invitation']}; also "
                        f"{planet_frame['practice']}."
                    ),
                    blend_note=(
                        "When near a boundary, read this alongside the adjacent sign as "
                        "two symbolic lenses rather than a fractional identity."
                    ),
                    planet=planet,
                    sign=sign,
                )
            )

    if len(records) != SEED7_READY_COUNT:
        raise AssertionError(
            f"Seed 7 bug: expected {SEED7_READY_COUNT}, generated {len(records)}"
        )
    if any(entry.status != "ready" or entry.source != "original" for entry in records):
        raise AssertionError("Seed 7 must contain only original ready records")
    if any(entry.version <= 1 for entry in records):
        raise AssertionError("Seed 7 records must upgrade the v1 inventory stubs")
    if any(len(entry.summary) < 100 for entry in records):
        raise AssertionError("Seed 7 summaries must be substantive")
    if len({entry.id for entry in records}) != len(records):
        raise AssertionError("Seed 7 generator produced duplicate ids")
    return tuple(records)


def expected_entry_ids(*, include_patterns: bool = True) -> tuple[str, ...]:
    entries = generate_seed0_entries()
    if not include_patterns:
        entries = tuple(entry for entry in entries if entry.type != "pattern")
    return tuple(entry.id for entry in entries)


def seed_payload(seed_id: str, entries: Iterable[InterpretationEntry]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "seed_id": seed_id,
        "records": [entry.to_dict() for entry in entries],
    }
