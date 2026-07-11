# Codex implementation prompt — Sidereal Moment Interpreter

Copy everything below the line into Codex (or another implementer). Work in:

`/mnt/c/Users/rober/Downloads/Projects/sidereal`

Authoritative requirements: **`SPEC.md` in this directory**. If this prompt and SPEC conflict, **SPEC wins**. If something is ambiguous, choose the option that maximizes **calculational correctness** and **explicitness**, not marketing flair.

---

## Mission

Build a **local, offline-first Python tool** that:

1. Takes **any datetime + timezone** (optional time, optional lat/lon).  
2. Computes planetary positions with **Swiss Ephemeris**.  
3. Maps them into the **13-sign true-sidereal Midpoint** zodiac (unequal signs, includes **Ophiuchus**).  
4. Computes **12 equal houses from the Ascendant** when time+location exist.  
5. Computes **major aspects** (and applying/separating).  
6. Joins results to a **SQLite interpretation database** covering:
   - planet in sign  
   - planet in house  
   - sign on house  
   - aspect relationships  
7. Emits **JSON + Markdown** reports.  
8. Never pretends interpretation is science; never invents houses when time is unknown.

Ship **Phase 1 + Phase 2** from SPEC §10 (engine + interpretation store with full stub inventory + Seed 0/1 text where specified).

---

## Non-negotiables

1. Read and follow `SPEC.md` completely.  
2. **Epistemic split:** geometry vs interpretation (SPEC §1). Surface this in Markdown reports.  
3. **Do not scrape or copy** interpretive text from masteringthezodiac.com or other commercial sites.  
4. **Do not** implement Midpoint as “Lahiri ayanamsa + 30° signs.” Use the **unequal J2000 boundary table** in SPEC §3.2; ship it as `data/boundaries/midpoint_j2000_v1.json`.  
5. **Unknown time:** planets OK; no Asc/MC/houses/aspects-to-angles.  
6. Modules stay focused; prefer clear types (dataclasses) over god-files.  
7. Tests required (SPEC §8.1).  
8. No network calls required to compute a chart after ephemeris files are present.

---

## Tech choices (do not bikeshed)

- Python 3.11+  
- `pyswisseph` for ephemeris  
- `zoneinfo` for timezones  
- SQLite for interpretation DB  
- `pyproject.toml` with installable package `sidereal`  
- CLI: `python -m sidereal ...`  
- pytest for tests  

If `pyswisseph` install is problematic on the machine, document the exact install steps in README and still structure the code against a thin `ephemeris.py` interface so tests can mock if needed — but **prefer real SE** in CI/local when available.

---

## Deliverables (filesystem)

Create the layout in SPEC §7.2. Minimum deliverables:

```
sidereal/
  SPEC.md                 # already exists — do not dilute
  CODEX_PROMPT.md         # already exists
  README.md               # how to install, run, epistemic note
  pyproject.toml
  CLAUDE.md               # short project guide for future agents
  src/sidereal/           # package
  data/boundaries/midpoint_j2000_v1.json
  data/seeds/*.json       # interpretation seeds
  tests/
  .gitignore              # charts/, reports/, venv, __pycache__, large ephe if needed
```

---

## Implementation order (strict)

### Step 1 — Scaffold

- Package, pyproject, gitignore, CLAUDE.md, README skeleton  
- `types.py` with frozen dataclasses for inputs, points, aspects, chart, report  

### Step 2 — Boundary data + zodiac mapper

- Write `midpoint_j2000_v1.json` exactly from SPEC §3.2  
- Implement circular segment membership + `degree_in_sign` + `blend` (±3°)  
- Tests: lengths sum 360; no gaps; sample longitudes → expected signs  

### Step 3 — Time + ephemeris

- Local date/time/tz → UT → Julian Day  
- Positions for Sun–Pluto + true Node (+ South Node as +180°)  
- Convert longitudes for Midpoint mapping per SPEC §3.3 (document method in code comments + README)  
- Test: one fixed JD matches SE expected sun longitude within tight tolerance  

### Step 4 — Houses + angles

- When time+lat+lon present: Asc, MC, Desc, IC  
- Default house system: **equal 12 from Asc** (`equal_house_12`)  
- Assign each body a house 1–12  
- Map each cusp longitude through Midpoint for `sign_on_house`  

### Step 5 — Aspects

- Majors only by default: conjunction, opposition, trine, square, sextile  
- Orbs per SPEC §5.1  
- Applying/separating from longitudinal speeds  
- Canonical body pair ordering for stable IDs  

### Step 6 — Chart orchestrator

- `chart.compute(MomentInput, config) -> Chart`  
- JSON serialization (stable keys, sorted where helpful)  

### Step 7 — Interpretation DB

- SQLite schema for entries (SPEC §6.3 fields)  
- `db init`, `db import`, `db get`, `db gaps`  
- Generator that creates **stub records for the full key inventory**:
  - 13 signs, 12 houses, all planets  
  - all planet_in_sign, planet_in_house, sign_on_house  
  - all major aspects for required body set (unordered pairs, sorted ids)  
  - angle_in_sign for asc/mc × 13 signs  
- **Seed 1 quality text** (not mere empty stubs) for:
  - all 13 `sign:*`  
  - all 12 `house:*`  
  - all `planet:*`  
  - `planet_in_sign` for sun, moon × all 13 signs  
  - `angle_in_sign` for asc × all 13 signs  
- All other keys may remain `status: stub` with keywords + one placeholder sentence  
- Tone: clear, non-fatalistic, no medical/financial claims, Ophiuchus first-class  

### Step 8 — Report composer

- Markdown + JSON report per SPEC §9  
- Includes epistemic note, placements, sign-on-house, relationships, patterns (patterns can be empty list if detector not done — but implement stellium at least)  
- Explicit **Missing interpretation keys** section  

### Step 9 — CLI

Implement commands from SPEC §7.4 at least:

- `chart`  
- `db init` / `db import` / `db gaps` / `db get`  

### Step 10 — README + self-check

- Install, ephemeris file setup, example command  
- Epistemic disclaimer  
- Run pytest; fix failures  

---

## Aspect body set for DB keys (v1)

Bodies participating in aspect interpretation keys:

`sun, moon, mercury, venus, mars, jupiter, saturn, uranus, neptune, pluto, north_node, asc, mc`

(Only include asc/mc aspect rows in reports when time known; keys may still exist in DB.)

Major aspect types for keys:  
`conjunction, opposition, trine, square, sextile`

---

## Content writing guidelines for seeds you author

- Original wording only.  
- 1–4 sentences for Seed 1 “real” entries; stubs = 1 sentence + keywords.  
- Prefer psychological / symbolic language: “associated with,” “traditionally read as.”  
- Never claim inevitability.  
- Ophiuchus: coherent themes (integration, healing-as-metaphor not medicine, liminality, knowledge under pressure) without copying MTZ.  
- Unequal signs: do not mention “30°” as a universal truth.  

---

## Acceptance criteria (you must verify)

- [ ] `pytest` passes  
- [ ] `python -m sidereal chart --date 2000-01-01 --time 12:00 --tz UTC --lat 0 --lon 0 --md /tmp/t.md --out /tmp/t.json` works  
- [ ] Chart JSON includes Midpoint signs; Ophiuchus appears for a sun sample that falls inside the published Midpoint bounds (J2000-era: ~Dec 7–18; document in tests — do not invent late-November if the table says otherwise) 
- [ ] Unknown time path works without houses  
- [ ] DB has full key inventory; Seed 1 keys are non-stub  
- [ ] Report lists gaps for stubs when those keys are hit  
- [ ] README documents boundary attribution (Chimenti / Zenodo DOI) and SE dependency  

---

## Out of scope (do not do now)

- Web UI, accounts, geocoding API  
- Placidus (unless trivial via SE and behind flag)  
- Transits/synastry UI  
- Scraping MTZ  
- LLM calls at runtime  
- 13-house systems  

---

## When stuck

1. Prefer SPEC defaults.  
2. Prefer **explicit failure** over guessed birth times or silent wrong frames.  
3. Leave a short `IMPLEMENTATION_NOTES.md` only if you had to choose a precession algorithm detail — state what you did and how to re-validate.  
4. Do not expand scope to pretty graphics.

---

## Definition of done

Phase 1 + Phase 2 complete: installable package, tests green, CLI chart+db commands, Midpoint 13-sign mapping, equal houses, major aspects, SQLite interpretation DB with full stubs + Seed 1 text, JSON/Markdown reports with epistemic note and gap listing.

Start implementing now. Do not wait for clarification on aesthetic choices. If a single technical clarification is truly blocking (e.g. pyswisseph unavailable), implement the interface + mocks, document the blocker in README, and continue.
