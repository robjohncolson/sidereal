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
