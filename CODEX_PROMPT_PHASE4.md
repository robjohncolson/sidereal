# Codex implementation prompt — Sidereal Phase 4

Work in:

`/mnt/c/Users/rober/Downloads/Projects/sidereal`

**Authority:** `SPEC.md` > this prompt > `CLAUDE.md` > existing code.
**Epistemic split is non-negotiable:** geometry is astronomy; interpretation is symbolic study notes — never claim scientific proof, fate, medical, or financial outcomes.

---

## Already shipped (do not rebuild)

| Phase | Commit-ish | What |
|-------|------------|------|
| 1–2 | `d0473e2` | Engine, Midpoint 13, houses, aspects, SQLite, Seeds 0–2 |
| 3 | `e5bdf74` | Seed 3 placements, tropical compare, save/list/show/interpret |

**Current inventory:** 437 ready / 475 stub / 0 missing · **122 tests** green
**Default zodiac:** Midpoint unequal 13 (Ophiuchus first-class)
**Houses:** equal 12 from Asc
**Library:** `charts/` JSON (gitignored)
**Ephemeris:** optional local `data/ephe/*.se1` (gitignored — never commit)

### Remaining stubs (targets for Seeds 4–5)

| Type | Stub ≈ | Priority |
|------|--------|----------|
| `aspect` | 285 | Seed 5 — personal↔outer, personal↔angles first |
| `planet_in_sign` | 130 | Seed 4 — Mercury/Venus/Mars first; outers second |
| `planet_in_house` | 60 | Seed 4 — Uranus–Pluto + nodes |

---

## Mission (Phase 4)

Deliver four coordinated workstreams in **this order** (dependencies matter):

1. **Seed 4 + Seed 5 content** — fill the highest-value remaining interpretation keys
2. **Polish** — chart-scoped gaps, better UX of CLI errors, report quality
3. **Transits** — second moment vs a saved natal (or two moments)
4. **Local web UI** — browser form + report viewer talking to a **local** Python server

Do **not** start the web UI until Seeds 4–5, polish, and transit **engine + CLI** work and are tested. The web layer must call the same code paths as the CLI (no second calculation stack).

---

## Non-negotiables

1. No interpretive prose in geometry modules (`chart.py`, `ephemeris.py`, `aspects.py`, `houses.py`, `zodiac/*`).
2. Midpoint remains unequal 13-segment J2000 map — never ayanamsa + 30°.
3. Unknown time: no Asc/MC/houses/angle aspects; transit to angles requires natal time known.
4. Seeds: deterministic generators in `schema.py` / `generate_seeds.py`; higher `version` upgrades stubs; original non-fatalistic wording; Ophiuchus first-class.
5. Dual ephemeris goldens (Moshier vs `swisseph`) stay valid.
6. Never commit `.se1`, `*.db`, `charts/`, `reports/`, `.venv/`, `dist/`.
7. Web server is **localhost-only by default** (bind `127.0.0.1`); no accounts, no cloud, no telemetry.
8. Comparison and transit copy must not declare one zodiac “true.”

---

# Workstream 1 — Seed 4 content (placements)

**File:** `data/seeds/seed_4_placements_v1.json`
**Generator:** `generate_seed4_entries()` · constant `SEED4_READY_COUNT`

### Required ready keys

| Set | Count | IDs |
|-----|------:|-----|
| Mercury, Venus, Mars × 13 signs | 39 | `planet_in_sign:{p}:{sign}` |
| Uranus, Neptune, Pluto, North Node, South Node × 12 houses | 60 | `planet_in_house:{p}:{h}` |
| **Total Seed 4** | **99** | |

Quality bar (same as Seed 1–3):

- `status: ready`, `source: original`, `version: 2+`
- summary ≥ ~100 characters, non-fatalistic
- houses = life-arena metaphors; nodes = calculated points not planets
- Ophiuchus entries real (not “see Scorpio”)
- optional `growth` one-liner

### Optional Seed 4 stretch (only after required 99)

Jupiter/Saturn already have house text; do **not** redo.
Optional: `planet_in_sign` for Jupiter/Saturn × 13 (26) if time remains after Workstream 1 tests green.

---

# Workstream 2 — Seed 5 content (relationships)

**File:** `data/seeds/seed_5_relationships_v1.json`
**Generator:** `generate_seed5_entries()` · `SEED5_READY_COUNT`

### Required ready keys

Major aspects only (`conjunction, opposition, trine, square, sextile`):

1. **Personal ↔ outer/node**
   Personal = `sun, moon, mercury, venus, mars, jupiter, saturn`
   Outer/node = `uranus, neptune, pluto, north_node`
   All unordered pairs × 5 aspects → **140** keys

2. **Personal ↔ angles**
   Angles = `asc, mc`
   All pairs with personal bodies × 5 → **70** keys

3. **Luminaries ↔ remaining** already partly covered by Seed 2; do not duplicate.
   Seed 5 must only emit keys still stubbed (or always emit ready records with version≥2 so import upgrades).

**Total Seed 5 required ≈ 210** (exact count: compute from inventory; assert no duplicates vs Seeds 2–4).

### Optional Seed 5 stretch

- Outer↔outer majors (Uranus/Neptune/Pluto pairs)
- South Node aspects (if not already in inventory as aspect bodies — **check `ASPECT_BODIES`**; do not invent keys outside inventory)

### After Seeds 4+5 import (expected)

Approximate: `437 + 99 + 210 ≈ 746 ready` / `~166 stub` / `0 missing`
(Adjust if inventory math differs; tests must assert exact generator counts.)

Update README / CLI audit expectations / inventory tests accordingly.

---

# Workstream 3 — Polish

### 3.1 Chart-scoped gaps

```bash
python -m sidereal db gaps --db data/sidereal.db
python -m sidereal db gaps --db data/sidereal.db --chart reports/me.json
python -m sidereal db gaps --db data/sidereal.db --chart-id Me
```

- Default `gaps`: full inventory audit (existing)
- With `--chart` (report JSON) or `--chart-id` / saved label: only keys **hit by that chart’s composed report**
- Output JSON: `{ ready, stub, missing, stub_ids, ... }` scoped

### 3.2 Report polish

- Sort relationships by force/exactness (tightest first) — if not already
- Group placement readings clearly in Markdown (planet · sign · house)
- Surface blend zones more visibly (“within 3° of boundary”)
- Ensure comparison + transit sections use neutral framing

### 3.3 CLI ergonomics

- Actionable errors for missing SE files when `--require-swiss-ephemeris`
- `sidereal --help` documents new commands
- Consistent `--db`, `--charts-dir`, `--ephe-path` across subcommands

### 3.4 Docs

Update `README.md` and `CLAUDE.md` for Seeds 4–5, transits, web UI.
Short Phase 4 note in `IMPLEMENTATION_NOTES.md` only for non-obvious design choices.

---

# Workstream 4 — Transits

### Semantics

**Transit chart** = sky at moment T (any datetime + optional location).
**Natal chart** = saved library chart (preferred) or inline natal moment.

Compute:

1. Natal geometry (existing)
2. Transit geometry at T (planets; houses/angles for transit only if transit time+place known — default: **planets only** for transit body set unless user passes transit lat/lon/time fully)
3. **Natal–transit aspects:** each transit body to each natal body/angle (when natal time known), using same major aspect rules/orbs
4. Optional: transit sign/house overlays — transit planet in Midpoint sign; **house occupancy uses natal houses** (which natal house is the transit planet in?) when natal time known

### CLI

```bash
# Against a saved natal
python -m sidereal transit \
  --natal Me \
  --date 2026-07-11 --time 12:00 --tz America/New_York \
  --db data/sidereal.db \
  --md reports/transit.md --out reports/transit.json

# Inline natal (optional)
python -m sidereal transit \
  --natal-date ... --natal-time ... --natal-tz ... --natal-lat ... --natal-lon ... \
  --date ... --time ... --tz ... \
  ...
```

### Output

JSON + Markdown:

- Natal summary (label, moment)
- Transit moment
- Table: transit body → Midpoint sign (and natal house if available)
- List: transit–natal aspects with orb, applying/separating, interpretation lookup `aspect:{a}:{type}:{b}`
- Gaps for missing aspect text
- Epistemic note: “transits are geometric correlations for study, not predictions”

### Rules

- Reuse `compute_aspects` / orb config; do not fork orb logic
- Body set: same planets as natal; include transit Moon (fast — always label as time-sensitive)
- If natal `time_known=false`, omit aspects to Asc/MC and natal house placement of transit planets
- Tests with synthetic longitudes + one golden live chart (e.g. known square within 1°)

### Library integration

Optional: `python -m sidereal transit --natal Me --save-as "Me-transit-2026-07-11"` storing a transit report reference — nice-to-have, not required.

---

# Workstream 5 — Local web UI

### Architecture (required shape)

```
Browser (static UI)
    ↓ HTTP JSON  (127.0.0.1 only)
sidereal.web / FastAPI (or stdlib http.server + thin router)
    ↓
existing chart / transit / library / interpret / db code
```

- **No second ephemeris implementation in JavaScript.**
- Prefer **FastAPI** if already easy to add as optional dependency; otherwise a small stdlib or Flask server is fine — pick one, document it.
- Optional extra: `pip install -e ".[web]"`

### Server CLI

```bash
python -m sidereal serve --host 127.0.0.1 --port 8742 \
  --db data/sidereal.db \
  --charts-dir charts \
  --ephe-path data/ephe
```

- Default host **127.0.0.1** (refuse `0.0.0.0` unless `--allow-lan` explicit flag with warning)
- Serves static files from `src/sidereal/web/static/` (or `web/`)
- JSON API under `/api/...`

### Minimum API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | versions, ephemeris backend probe |
| POST | `/api/chart` | body = moment + options → full report JSON |
| POST | `/api/transit` | natal ref or inline + transit moment → transit report |
| GET | `/api/charts` | list saved |
| GET | `/api/charts/{id}` | show saved geometry |
| POST | `/api/charts` | save |
| POST | `/api/charts/{id}/interpret` | re-interpret |
| GET | `/api/db/gaps` | inventory or `?chart_id=` |
| GET | `/api/db/entry/{id}` | single interpretation entry |

Reuse CLI validation rules (tz, fold, lat/lon bounds, unknown time).

### Minimum UI pages (single-page or multi-file static)

1. **Chart form** — date, time (optional), tz, lat/lon, label, compare tropical checkbox, submit → render report
2. **Report view** — sections: meta, epistemic note, angles, planets, houses, placements, relationships, comparison, gaps
3. **Library** — list saved charts; open; re-interpret; run transit against selected natal
4. **Transit form** — pick natal + transit datetime

### UX quality bar (personal tool, not product marketing)

- Readable typography, clear hierarchy, mobile-usable width
- Dark or light theme — one good default is enough
- Glyphs optional; plain planet names fine
- Show stubs distinctly (e.g. muted “stub” badge) vs ready text
- Never hide the epistemic note
- Loading and error states for API failures

### Security / privacy

- Localhost default
- No analytics
- Document that birth data stays on machine
- CORS: only needed if separating origins; prefer same-origin static+API

### Tests

- API tests via FastAPI `TestClient` (or equivalent) for chart + transit + list
- Optional snapshot of HTML contains epistemic note string
- Do not require a real browser driver

---

## Implementation order (strict)

```
1. Seed 4 generator + JSON + tests
2. Seed 5 generator + JSON + tests
3. Full db import audit counts
4. Polish: scoped gaps + report/CLI nits
5. Transit engine module + CLI + tests
6. serve + API wrapping existing functions
7. Static web UI consuming API
8. README / CLAUDE / smoke script
9. pytest full suite + manual smoke
10. Commit on main
```

---

## Acceptance checklist

### Content
- [ ] Seed 4: 99 required ready keys present and substantive
- [ ] Seed 5: ~210 personal↔outer and personal↔angle aspects ready
- [ ] `db gaps` → 0 missing; ready count matches tests
- [ ] Sample natal report: far fewer stubs on personal placements/aspects

### Polish
- [ ] `db gaps --chart` / `--chart-id` scopes to hit keys
- [ ] Help text and README cover new features

### Transits
- [ ] `transit` CLI produces JSON+MD with natal–transit aspects
- [ ] Unknown natal time path omits angle/house transit features
- [ ] Tests green

### Web
- [ ] `sidereal serve` on 127.0.0.1 serves UI + API
- [ ] Can compute a chart and view placements/aspects in browser
- [ ] Can list a saved chart and run a transit from UI
- [ ] No `.se1` or birth DB committed

### Regression
- [ ] Prior Midpoint/tropical/save behaviors unchanged
- [ ] Full pytest suite green (expect ~140+ tests)

---

## Out of scope (Phase 4)

- Cloud deploy, auth, multi-user
- Synastry (two natals) — design-compatible but not required
- Placidus / Vedic dashas / progressions
- Scraping commercial interpretive copy
- Runtime LLM generation of interpretations
- Exact MTZ visual clone
- WASM Swiss Ephemeris in the browser

---

## Manual smoke (must pass before commit)

```bash
cd /mnt/c/Users/rober/Downloads/Projects/sidereal
source .venv/bin/activate
python -m pip install -e ".[dev,web]"   # or .[dev] if web deps folded in

python -m sidereal db init --db data/sidereal.db
python -m sidereal db import --db data/sidereal.db
python -m sidereal db gaps --db data/sidereal.db

python -m sidereal chart \
  --date 2000-12-12 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --compare tropical --db data/sidereal.db \
  --md /tmp/p4.md --out /tmp/p4.json

python -m sidereal db gaps --db data/sidereal.db --chart /tmp/p4.json

python -m sidereal save --label "Demo" \
  --date 2000-12-12 --time 12:00 --tz UTC --lat 0 --lon 0

python -m sidereal transit --natal Demo \
  --date 2026-07-11 --time 12:00 --tz UTC \
  --db data/sidereal.db --md /tmp/tr.md --out /tmp/tr.json

python -m sidereal serve --host 127.0.0.1 --port 8742 --db data/sidereal.db
# browser: open http://127.0.0.1:8742/  → chart + transit smoke
pytest
```

---

## Definition of done

Phase 4 is done when:

1. Interpretation coverage is **dense enough** for personal + outer relationships (Seeds 4–5).
2. You can study **transits to a saved natal** from CLI.
3. You can do chart + library + transit from a **local web page** without leaving the machine.
4. Tests and docs reflect reality; git commit is clean of secrets and ephemeris binaries.

Start with Seed 4. Do not open web UI work until transit CLI works.

---

## Orchestrator note

When finished, report: commit hash, new ready/stub counts, test count, and any intentional scope cuts. Prefer cutting optional stretches over shipping a broken web server.
