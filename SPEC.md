# Sidereal — Moment Interpreter Specification

**Project:** `sidereal`  
**Status:** Spec complete — ready for implementation  
**Owner role:** Orchestrator is truth-seeking; implementation may be delegated (e.g. Codex)  
**Last updated:** 2026-07-10

---

## 0. One-sentence goal

Given **any civil datetime + location** (or raw coordinates), compute a **13-sign true-sidereal Midpoint chart** and assemble a **complete structured interpretation** covering: planet-in-sign, planet-in-house, sign-on-house (cusps), and **relationships among placements** (aspects + major patterns), backed by a local **interpretation database**.

---

## 1. Epistemic contract (non-negotiable)

This project has two layers with different truth claims. **Never conflate them in code, UI, or copy.**

| Layer | What it is | Truth standard |
|-------|------------|----------------|
| **A. Astronomy / geometry** | Julian day, planetary ecliptic longitudes, house cusps, angular separations, Midpoint boundary membership | Reproducible against Swiss Ephemeris + published boundary table. Unit-tested. |
| **B. Interpretation** | Meanings of signs, houses, planets, aspects | Symbolic / cultural framework for personal study. **Not empirical science.** Must be labeled as interpretive. |

### Hard rules

1. **No scientific overclaim.** Do not say placements “prove” personality, fate, or health. Prefer language: “traditional reading,” “symbolic associations,” “working notes.”
2. **Calculation is sacred.** Wrong longitudes invalidate everything downstream. Prefer failing loudly over silent wrong charts.
3. **Do not scrape or copy** Mastering the Zodiac (or any commercial site) interpretive prose. Boundaries may be implemented from **published Midpoint Method data** (cited). Interpretive text must be original stubs, user-authored, or clearly licensed.
4. **Sources of boundaries and of meaning must be citable** in data files (`source`, `license`, `version` fields).
5. **Unknown birth time** is first-class: planets without houses/angles still work; UI must not invent Asc/MC.

---

## 2. User-facing product (personal tool)

### 2.1 Primary use case

> “I pick a moment (birth, transit, event). I get the full 13-sign chart for that moment and a readable report that walks every placement and every major relationship, with my notes database behind it.”

### 2.2 Inputs

| Field | Required | Notes |
|-------|----------|-------|
| Local date | Yes | Calendar date |
| Local time | No | If missing → `time_known=false`; skip houses/angles/aspects to angles |
| Timezone | Yes if time known | IANA preferred (`America/New_York`); offset fallback allowed |
| Latitude / longitude | Yes if houses needed | Degrees decimal |
| Place name | No | For display; geocoding optional in v1 |
| Chart label | No | e.g. “Me”, “Event X” |
| Zodiac system | Default Midpoint | Extensible enum (see §4) |
| House system | Default Whole Sign | Placidus optional later |
| Aspect orb profile | Default modern | Named presets in config |

### 2.3 Outputs (always machine-readable JSON + human report)

1. **Meta** — inputs, JD(UT), systems used, library versions, boundary version  
2. **Points** — each body/angle: tropical lon, mapped sign, degree-in-sign, house, speed, retrograde, cusp-blend flags  
3. **Houses** — 12 cusps (if time known), sign on each cusp  
4. **Aspects** — pairwise relationships with type, exactness, orb, applying/separating  
5. **Patterns** — stelliums, T-squares, grand trines, oppositions stacks (v1 minimal)  
6. **Interpretation bundle** — joined text/records from the DB for every applicable key  
7. **Gaps** — list of missing DB entries (so incomplete lore is visible, not silent)

### 2.4 Non-goals (v1)

- User accounts, email reports, marketing  
- Exact pixel clone of MTZ UI  
- Vedic dashas, divisional charts, synastry/transits UI (data model may allow later)  
- Claiming Midpoint is the only “correct” zodiac  
- Mobile app store packaging  

---

## 3. Zodiac: 13-sign Midpoint Method (default)

### 3.1 Definition

**True sidereal Midpoint** (Chimenti / Mastering the Zodiac):

- Unequal constellation spans along the **ecliptic**  
- **13 signs**, including **Ophiuchus** between Scorpio and Sagittarius  
- Boundaries = midpoints between edge **constellation line stars** (IAU/Vedic figures as documented by the method)  
- Reference: published boundary longitudes in **J2000 ecliptic**  

Primary citable source for the method and table:

- Chimenti, A. (2026). *The Midpoint Method: An Ecliptic-Based Boundary System for Zodiacal Constellations.* Zenodo. https://doi.org/10.5281/zenodo.20747017  
- Summary table also published at: https://masteringthezodiac.com/midpoint-method  

### 3.2 Canonical boundary table (J2000 ecliptic longitude, degrees)

These are **start longitudes** of each sign, reconstructed so consecutive starts differ by published sign lengths and wrap correctly through 360°.

| Order | Sign ID | Display name | Start λ (J2000°) | Length (°) |
|------:|---------|--------------|-----------------:|-----------:|
| 1 | `aries` | Aries | 31.2816 | 19.7267 |
| 2 | `taurus` | Taurus | 51.0083 | 36.8572 |
| 3 | `gemini` | Gemini | 87.8655 | 29.4539 |
| 4 | `cancer` | Cancer | 117.3194 | 17.1495 |
| 5 | `leo` | Leo | 134.4689 | 38.4195 |
| 6 | `virgo` | Virgo | 172.8884 | 49.7185 |
| 7 | `libra` | Libra | 222.6069 | 18.8784 |
| 8 | `scorpio` | Scorpio | 241.4853 | 13.2279 |
| 9 | `ophiuchus` | Ophiuchus | 254.7132 | 12.3578 |
| 10 | `sagittarius` | Sagittarius | 267.0711 | 33.3912 |
| 11 | `capricorn` | Capricorn | 300.4622 | 25.6690 |
| 12 | `aquarius` | Aquarius | 326.1312 | 23.1646 |
| 13 | `pisces` | Pisces | 349.2959 | 41.9857 |

**Invariant:** start\[i+1\] ≡ start\[i\] + length\[i\] (mod 360). Sum of lengths = 360° (±0.001° tolerance).

Ship this table as versioned data:

```
data/boundaries/midpoint_j2000_v1.json
```

Include: `version`, `frame: "ecliptic_j2000"`, `source`, `doi`, `signs[]`.

### 3.3 Mapping algorithm (normative)

```
1. Compute tropical ecliptic longitude λ_date of the point (Swiss Ephemeris, true equator/ecliptic of date).
2. Convert λ_date → λ_j2000 in the same ecliptic J2000 frame as the boundary table.
   (Implementation must document the exact SE flags / precession path used.)
3. Find sign S such that λ_j2000 is in [start_S, start_S + length_S) along the circle.
4. degree_in_sign = arc_distance(start_S, λ_j2000)
5. cusp_blend = true if distance to nearest boundary ≤ BLEND_ORB (default 3.0°)
   When blend: attach secondary_sign = the adjacent sign across that boundary.
```

**Critical:** Do **not** apply a single constant ayanamsa to equal 30° signs and call it Midpoint. Midpoint is **unequal segments**.

### 3.4 Optional systems (extensibility)

Implement Midpoint first. Design `ZodiacMap` as an interface so later systems can plug in without rewrite:

| System ID | Kind | Notes |
|-----------|------|-------|
| `midpoint_v1` | unequal 13 | Default |
| `iau_ecliptic` | unequal 13 | Optional; different boundaries; do not pretend identical to Midpoint |
| `lahiri` | equal 12 | Sidereal ayanamsa; no Ophiuchus |
| `fagan_bradley` | equal 12 | Western sidereal |
| `tropical` | equal 12 | Seasons; comparison mode |

Equal-sign systems use classic 30° slices after ayanamsa (or tropical identity).

---

## 4. Points computed

### 4.1 Bodies (v1 required)

| ID | Name | SE body |
|----|------|---------|
| `sun` | Sun | SE_SUN |
| `moon` | Moon | SE_MOON |
| `mercury` | Mercury | SE_MERCURY |
| `venus` | Venus | SE_VENUS |
| `mars` | Mars | SE_MARS |
| `jupiter` | Jupiter | SE_JUPITER |
| `saturn` | Saturn | SE_SATURN |
| `uranus` | Uranus | SE_URANUS |
| `neptune` | Neptune | SE_NEPTUNE |
| `pluto` | Pluto | SE_PLUTO |
| `north_node` | North Node (true) | SE_TRUE_NODE |
| `south_node` | South Node | opposite of north node |

### 4.2 Optional bodies (v1.1 flags)

Chiron, mean Lilith, Part of Fortune — behind feature flag; interpretation DB may omit until ready.

### 4.3 Angles (require time + location)

| ID | Name |
|----|------|
| `asc` | Ascendant |
| `mc` | Midheaven |
| `desc` | Descendant (asc + 180°) |
| `ic` | Imum Coeli (mc + 180°) |

### 4.4 Houses

**Default v1: Whole Sign**

- House 1 = entire sign of Ascendant  
- House 2 = next sign in zodiac order (13-sign order when using Midpoint)  
- …  
- Under 13-sign Midpoint, **whole sign still uses 12 houses**. Spec choice:

**Normative choice for Midpoint + Whole Sign:**

1. Compute Asc longitude → map to Midpoint sign S.  
2. House 1 = S.  
3. Subsequent houses follow the **13-sign cyclic order**, but only **12 houses** exist → **one sign is skipped as a house cusp sign each chart**, OR we use **12 equal house divisions** of the ecliptic starting at Asc.

These conflict. Resolve as follows (truth-seeking, explicit):

| Mode | ID | Behavior |
|------|-----|----------|
| **A (default)** | `whole_sign_12_from_asc` | Traditional 12 houses: house n starts at Asc sign + (n−1) in a **12-sign projection**. For Midpoint charts, **project** by ignoring Ophiuchus for house labeling only: use 12 classical signs for house sequence starting from Asc’s classical twin if Asc is Ophiuchus → treat Ophiuchus Asc as “Scorpio/Sag boundary house logic” — **too messy**. |
| **B (recommended default)** | `equal_house_12` | 12 houses of 30° each starting at Asc longitude (tropical of date for house math; then map each cusp through Midpoint for sign-on-cusp). Clean, classic, works with any zodiac map. |
| **C** | `whole_sign_13` | Experimental: 13 houses, one per Midpoint sign. **Out of scope v1** (breaks all traditional house lore). |

**v1 default: `equal_house_12`** (Mode B).  
Document why: twelve-house interpretation corpus does not have a settled 13-house tradition; equal houses from Asc remain well-defined for any moment.

Optional later: Placidus via Swiss Ephemeris (`SEFLG` houses).

---

## 5. Aspects & relationships

### 5.1 Aspect types (v1)

| ID | Angle (°) | Default orb (°) | Class |
|----|----------:|----------------:|-------|
| `conjunction` | 0 | 8 | major |
| `opposition` | 180 | 8 | major |
| `trine` | 120 | 8 | major |
| `square` | 90 | 7 | major |
| `sextile` | 60 | 6 | major |
| `quincunx` | 150 | 3 | minor |
| `semisextile` | 30 | 2 | minor |
| `semisquare` | 45 | 2 | minor |
| `sesquiquadrate` | 135 | 2 | minor |

**Orb modifiers (v1):**

- If either body is Sun or Moon: +1° to default (capped).  
- If both are outer (Uranus/Neptune/Pluto): −2° (tighter).  
- Angles (Asc/MC) use same orbs as planets when time known.  
- Config file overrides all of the above.

### 5.2 Aspect computation

```
sep = shortest_arc(|λ_a − λ_b|)   # 0..180
for each aspect type with angle A and orb O:
  if |sep − A| ≤ O: match
exactness = |sep − A|
applying/separating from relative speeds along ecliptic (SE speed in long)
```

Store: `body_a`, `body_b` (canonical order by body sort key), `aspect_id`, `separation`, `orb_used`, `exactness`, `force` (optional 0–1 = 1 − exactness/orb), `applying`.

### 5.3 Patterns (v1 minimal)

Detect and list (no fancy drawing required):

| Pattern | Rule (simplified) |
|---------|-------------------|
| Stellium | 3+ bodies in same Midpoint sign (exclude outer-only-only noise: require ≥1 personal planet Sun–Mars or angles) |
| T-square | Two bodies in opposition, both square a third (orbs from profile) |
| Grand trine | Three bodies, each pair trine |
| Yod | Two quincunxes to an apex + sextile between base (optional if quincunx enabled) |

Patterns are **structural relationships** and each should resolve to interpretation keys when available.

### 5.4 “Relationship of the placements” — report order

Interpretation engine emits relationships in this priority:

1. Luminaries & angles to each other (Sun–Moon, Sun–Asc, Moon–Asc, Sun–MC, Moon–MC)  
2. Personal planet major aspects  
3. Social/outer major aspects to personal  
4. Minor aspects (if enabled)  
5. Patterns  

Each relationship line joins: geometric fact + DB meaning + user notes.

---

## 6. Interpretation database

### 6.1 Design principle

**Data, not hard-coded strings in engine code.**  
Engine only looks up keys. Missing keys → explicit `gap` entries.

### 6.2 Required content types

| Type | Key shape | Count (order of magnitude) | Meaning |
|------|-----------|----------------------------|---------|
| `sign` | `sign:{id}` | 13 | Constellation / sign overview |
| `house` | `house:{n}` | 12 | House life-area overview |
| `planet` | `planet:{id}` | ~12 | Body principle |
| `planet_in_sign` | `planet_in_sign:{planet}:{sign}` | ~12×13 ≈ 156 | Placement core |
| `planet_in_house` | `planet_in_house:{planet}:{house}` | ~12×12 ≈ 144 | Placement arena |
| `sign_on_house` | `sign_on_house:{sign}:{house}` | 13×12 = 156 | Sign coloring the house cusp / whole-house theme |
| `aspect` | `aspect:{a}:{type}:{b}` | C(n,2)×types, store non-ordered with sorted ids | Relationship meaning |
| `pattern` | `pattern:{type}` | ~5–10 | Pattern overview |
| `angle_in_sign` | `angle_in_sign:{asc|mc}:{sign}` | 2×13 | Identity / vocation tones |

**User request coverage mapping**

| User asked for | DB type |
|----------------|---------|
| each sign in each house | `sign_on_house` |
| each planet in the house | `planet_in_house` |
| each planet in the sign | `planet_in_sign` |
| relationship of placements | `aspect` + `pattern` (+ composed narrative) |

### 6.3 Record schema (JSON or SQLite — both OK; SQLite preferred)

```json
{
  "id": "planet_in_sign:sun:ophiuchus",
  "type": "planet_in_sign",
  "planet": "sun",
  "sign": "ophiuchus",
  "title": "Sun in Ophiuchus",
  "keywords": ["healing", "boundary-crossing", "integration"],
  "summary": "1–3 sentences. Neutral, non-medical, non-fatalistic.",
  "body": "Optional longer markdown.",
  "shadow": "Optional lower-expression notes.",
  "growth": "Optional development notes.",
  "blend_note": "Optional: how to read near cusps.",
  "source": "original|user|generated_draft",
  "license": "personal-use",
  "version": 1,
  "updated": "2026-07-10"
}
```

Aspect records use sorted planet ids: `aspect:mars:square:saturn` (alphabetical body order) + `aspect_type`.

### 6.4 Content policy (truth-seeking)

1. **v1 may ship with incomplete text** but **must ship complete key inventory** (stubs allowed).  
2. Stubs format: keywords + one-sentence placeholder + `"status": "stub"`.  
3. **No medical, financial, or crisis claims.**  
4. Ophiuchus entries must exist (not “see Scorpio”).  
5. Generated drafts (if used) must be marked `source: generated_draft` and are not “verified tradition.”  
6. Prefer plain language over mystical inflation.

### 6.5 Composition rules for a full report

For a chart with time known, for each body B in houses:

1. Emit `planet:{B}` (once in glossary section or first use)  
2. Emit `planet_in_sign:{B}:{S}`  
3. Emit `planet_in_house:{B}:{H}`  
4. For each house cusp sign C_h: emit `sign_on_house:{C_h}:{h}` (once per house)  
5. For Asc/MC: emit `angle_in_sign`  
6. For each aspect: emit geometry + `aspect:…`  
7. For each pattern: emit `pattern:…`  
8. Append any `notes` the user stored under chart id  

For blend placements: include both signs’ planet_in_sign summaries with a clear “within 3° of boundary” header.

### 6.6 Seeding strategy (implementation phases)

| Phase | Content |
|-------|---------|
| Seed 0 | All keys exist as stubs; 13 sign + 12 house + planets full short summaries |
| Seed 1 | All `planet_in_sign` for Sun, Moon, Asc + all signs |
| Seed 2 | All major `aspect` pairs among Sun, Moon, Mercury, Venus, Mars, Jupiter, Saturn |
| Seed 3 | Remaining planet_in_sign, planet_in_house, sign_on_house |
| Seed 4 | Minors + patterns + outers polish |

Engine must work at Seed 0 (report shows stubs + gap list).

---

## 7. Architecture

### 7.1 Recommended stack

| Piece | Choice | Rationale |
|-------|--------|-----------|
| Language | Python 3.11+ | Best Swiss Ephemeris bindings; easy DB; good for Codex |
| Ephemeris | `pyswisseph` + SE ephemeris files | Accuracy / industry standard |
| Interpretation store | SQLite (`data/sidereal.db`) + JSON seed import | Queryable, portable |
| CLI | `python -m sidereal ...` | Primary interface v1 |
| Report | Markdown + JSON out | Personal use, Obsidian-friendly |
| Web UI | Optional static HTML later | Not blocking |

### 7.2 Module map

```
sidereal/
  SPEC.md
  CODEX_PROMPT.md
  README.md
  pyproject.toml
  CLAUDE.md
  src/sidereal/
    __init__.py
    __main__.py
    types.py              # frozen dataclasses / enums
    timebase.py           # local → UT → Julian Day
    ephemeris.py          # SE wrapper: positions, speeds, houses
    zodiac/
      base.py             # ZodiacMap protocol
      midpoint.py         # Midpoint v1
      equal_sidereal.py   # future
      tropical.py
    houses.py             # equal_house_12, etc.
    aspects.py            # pairwise + patterns
    chart.py              # orchestrate Chart computation
    interpret/
      store.py            # SQLite access
      compose.py          # join chart + DB → Report
      schema.py
    cli.py
    config.py
  data/
    boundaries/midpoint_j2000_v1.json
    seeds/                # JSON files imported to SQLite
    ephe/                 # SE files or download instructions (.gitignore large files if needed)
  tests/
    test_boundaries.py
    test_zodiac_map.py
    test_aspects.py
    test_chart_golden.py
    fixtures/
  charts/                 # user saved charts (gitignored)
  reports/                # generated output (gitignored)
```

### 7.3 Core types (illustrative)

```python
@dataclass(frozen=True)
class MomentInput:
    local_date: date
    local_time: time | None
    tz: str
    lat: float | None
    lon: float | None
    label: str = ""

@dataclass(frozen=True)
class PointPos:
    id: str
    lon_date: float          # tropical ecliptic of date
    lon_j2000: float         # for Midpoint mapping
    lat: float
    speed_long: float
    retro: bool
    sign: str
    deg_in_sign: float
    house: int | None
    blend: bool
    secondary_sign: str | None

@dataclass(frozen=True)
class Chart:
    meta: ChartMeta
    points: tuple[PointPos, ...]
    cusps: tuple[HouseCusp, ...] | None
    aspects: tuple[AspectHit, ...]
    patterns: tuple[PatternHit, ...]
```

### 7.4 CLI (v1)

```bash
# Compute + interpret
python -m sidereal chart \
  --date 1990-06-15 \
  --time 14:30 \
  --tz America/New_York \
  --lat 40.7128 --lon -74.0060 \
  --label "Example" \
  --out reports/example.json \
  --md reports/example.md

# Planets only (unknown time)
python -m sidereal chart --date 1990-06-15 --tz UTC --no-houses

# DB tools
python -m sidereal db init
python -m sidereal db import data/seeds/
python -m sidereal db gaps          # list stub/missing keys for last chart types
python -m sidereal db get planet_in_sign:sun:virgo
```

### 7.5 Config defaults (`config.yaml` or env)

- `zodiac: midpoint_v1`  
- `house_system: equal_house_12`  
- `blend_orb_deg: 3.0`  
- `aspect_profile: modern_major` (minors off by default)  
- `nodes: true`  
- `ephe_path: data/ephe`  

---

## 8. Accuracy & testing requirements

### 8.1 Golden tests

1. **Boundary invariants** — lengths sum to 360; no gaps/overlaps.  
2. **Known Sun Midpoint date windows** — for J2000-era dates, Sun sign dates should align with published Midpoint sun-sign tables within ~1 day (document fixture sources from MTZ sun-sign list / Zenodo).  
3. **Swiss Ephemeris sanity** — Sun longitude on 2000-01-01 noon TDT matches published value within 1".  
4. **Aspect math** — synthetic longitudes produce expected aspects/orbs.  
5. **Unknown time** — no crash; houses/angles/aspects-to-angles absent.  
6. **Report gaps** — with empty DB, report still builds and lists gaps.

### 8.2 Validation protocol (orchestrator)

Before calling the tool “correct”:

1. Compare one full chart’s planet longitudes to astro.com or SE PHP test page (tropical).  
2. Map those longitudes through Midpoint table by hand for 2–3 bodies.  
3. Confirm Ophiuchus can appear for Sun under the published Midpoint bounds
   (J2000-era fixture: roughly **2000-12-07 through 2000-12-18** noon UT;
   late November is still Scorpio under these numbers — prefer the table over folklore dates).  
4. Confirm blend flag within 3° of a boundary.

### 8.3 Performance

Interactive CLI < 2s per chart on a laptop after ephemeris warm-up. No network required at compute time.

---

## 9. Report format (Markdown)

```markdown
# Chart: {label}
Moment: {local} ({tz}) → JD(UT) {jd}
System: Midpoint v1 (13-sign) · Houses: Equal 12 from Asc · Orbs: {profile}

## Epistemic note
Positions are astronomical. Interpretations are symbolic study notes, not scientific claims.

## Angles
...
## Planets
For each: Sign, degree, house, retro, blend
## Sign on each house
...
## Placement readings
### Sun in Virgo (house 5)
(planet_in_sign)
(planet_in_house)
...
## Relationships
### Moon square Saturn (orb 1.2°, applying)
...
## Patterns
...
## Missing interpretation keys
- planet_in_sign:pluto:ophiuchus (stub)
```

JSON mirrors the same structure for tooling.

---

## 10. Implementation phases

### Phase 1 — Engine (must land first)

- Project scaffold, SE integration, timebase  
- Midpoint map + boundary file  
- Equal houses  
- Aspects (majors)  
- JSON chart output  
- Tests §8.1 items 1–5  

### Phase 2 — Interpretation store

- SQLite schema + seed import  
- Stub generator for full key inventory  
- Seed 0 + Seed 1 content  
- Markdown report composer  

### Phase 3 — Usability

- CLI polish, saved charts, gap command  
- Optional tropical comparison flag  
- README with worked example  

### Phase 4 — Enrichment (optional)

- Minor aspects, patterns, Placidus  
- Static web viewer  
- Transit mode (second moment vs natal)  

**Definition of done for “usable personal tool”:** Phase 1 + Phase 2 with Seed 0/1, passing tests, one real personal chart report generated offline.

---

## 11. Risks & honest limitations

| Risk | Mitigation |
|------|------------|
| Midpoint table transcription error | Encode invariants + cross-check Zenodo PDF when implementing |
| Precession frame mismatch vs MTZ software | Document SE conversion; golden sun-sign tests; accept ≤0.1° class errors only with investigation |
| 13 signs vs 12-house lore tension | Equal houses default; explicit in report |
| Interpretation quality / bias | Stubs + user notes; no scraped commercial copy |
| SE licensing | Comply with Swiss Ephemeris license for distribution |
| Timezone historical edge cases | Use `zoneinfo`; document pre-1970 caveats |

---

## 12. License & attribution

- **Code:** user choice (recommend MIT for personal tooling).  
- **Boundary data:** attribute Chimenti Midpoint Method + DOI; do not claim ownership of the method.  
- **Interpretive text:** original/user; not copied from commercial reports.  
- **Swiss Ephemeris:** follow Astrodienst license terms for the library and ephemeris files.

---

## 13. Acceptance checklist

- [ ] Any moment with date+tz → tropical positions  
- [ ] Midpoint 13-sign mapping including Ophiuchus (fixture dates follow boundary table, not folklore)  
- [ ] Blend flag at ±3° boundaries  
- [ ] Equal 12 houses when time+lat+lon present  
- [ ] Major aspects with orbs + applying/separating  
- [ ] Full interpretation key inventory in DB (stubs OK)  
- [ ] Report includes planet×sign, planet×house, sign×house, aspects  
- [ ] Gaps listed when text missing  
- [ ] Unknown time path works  
- [ ] Tests green  
- [ ] README explains epistemic split and how to run  

---

## 14. Orchestrator notes

- Prefer **correct silent geometry** over pretty incomplete UI.  
- If implementation must choose between matching MTZ marketing copy and matching the **published boundary numbers**, choose the numbers.  
- If SE frame conversion is ambiguous, implement the simpler correct approach (precess positions to J2000 ecliptic), lock it in tests, and document.  
- Reject PRs that hardcode interpretive essays inside `chart.py`.
