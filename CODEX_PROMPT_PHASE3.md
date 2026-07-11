# Codex implementation prompt — Sidereal Phase 3

Work in:

`/mnt/c/Users/rober/Downloads/Projects/sidereal`

**Authority order:** `SPEC.md` > this prompt > `CLAUDE.md` > existing code style.
If anything conflicts with calculational correctness or the epistemic split (geometry ≠ interpretation), **SPEC and truth-seeking win**.

---

## Context (already done — do not rebuild)

Phase 1 + 2 are complete and committed on `main`:

- Swiss Ephemeris chart engine, Midpoint 13-sign map, equal houses, major aspects
- SQLite interpretation store + seed import/versioning
- Seeds: `seed_0` (912 stubs), `seed_1` (76 ready primers), `seed_2` (105 personal-planet major aspects)
- CLI: `chart`, `db init|import|get|gaps`
- **108 tests** green at handoff
- Ephemeris `.se1` files may exist locally under `data/ephe/` but are **gitignored** — never commit them

Inventory after Seed 2: **181 ready / 731 stub / 0 missing**.

Largest remaining stubs:

| Type | Stub count | Notes |
|------|------------|--------|
| aspect | 285 | outers, nodes, Asc/MC pairs |
| sign_on_house | 156 | sign coloring each house |
| planet_in_house | 144 | **user-requested core** |
| planet_in_sign | 130 | Mercury–Pluto × 13 (Sun/Moon done) |
| angle_in_sign | 13 | MC × 13 (Asc done) |
| pattern | 3 | stellium, t-square, grand trine |

---

## Mission (Phase 3)

Make the tool **actually useful for personal chart reading** without a web product:

1. **Seed 3 content** — ready text for the placement types the user asked for that are still stubs.
2. **Tropical comparison mode** — same moment, Midpoint vs tropical (equal 12), side-by-side in report/JSON.
3. **Saved charts library** — local JSON store under `charts/` (gitignored) with list/show/re-interpret.
4. **CLI + tests + docs** updated; keep geometry pure and interpretations in seeds/SQLite.

**Out of scope:** web UI, accounts, geocoding APIs, Placidus (unless already trivial behind a flag), synastry/transits, scraping commercial prose, runtime LLM calls, committing `.se1` binaries.

---

## Non-negotiables

1. Do **not** hardcode interpretive essays in `chart.py` / `ephemeris.py` / `aspects.py`.
2. Do **not** implement Midpoint as ayanamsa + 30° signs.
3. Unknown time still omits angles/houses/angle-aspects.
4. Seed upgrades use **higher `version`** than existing stubs (stubs are v1; ready seeds use v2+).
5. Deterministic seed generation: extend `generate_seeds.py` + `schema.py`; regenerate checked-in JSON; keep `check_seed_files` green.
6. Original wording only; symbolic, non-fatalistic; no medical/financial/crisis claims; Ophiuchus first-class.
7. Preserve dual ephemeris goldens (Moshier vs `swisseph`) in tests.
8. Report GitNexus impact before editing symbols if the monorepo Agents.md workflow applies; if GitNexus is unavailable for this nested repo, note that in `IMPLEMENTATION_NOTES.md` and proceed carefully.

---

## Deliverable A — Seed 3 content (required)

### A1. `planet_in_house` for personal planets (84 keys)

Bodies: `sun, moon, mercury, venus, mars, jupiter, saturn`
Houses: 1–12

Each ready record:

- `status: ready`, `source: original`, `version: 2` (or higher if key already ready)
- keywords + summary ≥ ~100 chars
- optional `growth` one-liner
- explicit that houses are life-arena metaphors, not predictions

IDs: `planet_in_house:{planet}:{house}`

### A2. `sign_on_house` for all 13 × 12 (156 keys)

Ready text for every Midpoint sign on every house cusp theme.
IDs: `sign_on_house:{sign}:{house}`
Include Ophiuchus on every house.

### A3. `angle_in_sign` for MC × 13 (13 keys)

Mirror Seed 1 Asc quality for Midheaven.
IDs: `angle_in_sign:mc:{sign}`

### A4. Pattern primers (3 keys)

Ready short summaries for `pattern:stellium`, `pattern:t_square`, `pattern:grand_trine` — structural, non-fatalistic.

### A5. Optional stretch (only if A1–A4 done and tests green)

`planet_in_sign` for `mercury, venus, mars` × 13 signs (39 keys).
Do **not** start outer-planet aspect essays in this phase unless everything else is done.

### Seed packaging

- Add `generate_seed3_entries()` in `schema.py`
- Export via `generate_seeds.py` → `data/seeds/seed_3_placements_v1.json` (name may vary; keep sorted stable name)
- Update `SEED3_READY_COUNT` and inventory tests
- Expected ready total after import:
  `181 + 84 + 156 + 13 + 3 [+ optional 39] = 437` without stretch, or **476** with Mercury–Mars in-sign

Update CLI/docs that mention 181/731 counts.

---

## Deliverable B — Tropical comparison mode (required)

Add a **comparison path** that does not replace Midpoint as default.

### Behavior

```bash
python -m sidereal chart ... --compare tropical
# or
python -m sidereal chart ... --compare midpoint,tropical
```

- Primary chart remains Midpoint (`midpoint_v1`) unless user sets another default later.
- Comparison computes the **same moment** with tropical equal-12 signs (classic 30° from 0° Aries tropical of date).
- Report includes a **Comparison** section:
  - For each body: Midpoint sign/deg vs tropical sign/deg
  - Flag where sign **labels** differ
  - Do **not** invent “which is true”; state both are different reference frames
- JSON: `comparison: { "systems": [...], "points": [ {id, systems: {...}} ] }`
- Houses for tropical comparison: same `equal_house_12` geometry; only the **sign mapping** of longitudes/cusps changes.
- Interpretation composition for the primary system only (avoid double DB spam). Comparison is geometry + labels.

### Implementation sketch

- Add `zodiac/tropical.py` implementing `ZodiacMap` (30° slices on **of-date** tropical longitude; no J2000 remap needed for sign labels).
- Midpoint continues to use J2000 longitudes + boundary table.
- Tests: known date Sun tropical Capricorn vs Midpoint Sagittarius around 2000-01-01; Ophiuchus never appears in tropical map.

---

## Deliverable C — Saved charts library (required)

Local-only persistence under `charts/` (already gitignored).

### Commands

```bash
python -m sidereal save --label "Me" --date ... --time ... --tz ... --lat ... --lon ...
python -m sidereal list
python -m sidereal show <chart_id_or_label> [--md path] [--out path]
python -m sidereal interpret <chart_id_or_label>   # re-compose with current DB
```

### Storage

- One JSON file per chart: `charts/{slug}-{utc_iso_or_shortid}.json`
- Contents: input moment, config used, full geometry chart (`Chart.to_dict()`), optional last report path
- **Do not** store secrets; birth data is sensitive — document that `charts/` is local/gitignored
- `list` prints id, label, local datetime, tz, systems
- Re-interpret uses stored inputs (or stored geometry if you prefer) + current SQLite DB

Keep implementation small: no SQLite for charts unless clearly cleaner; JSON files are fine.

---

## Deliverable D — CLI polish (required)

1. `db gaps --hit-by-chart <json|id>` optional stretch: list only stubs touched by a chart. If easy, include; else skip.
2. Chart command: clearer error if `--require-swiss-ephemeris` and files missing.
3. Default `--ephe-path` discovery already exists; document Seed 3 + compare + save in README.
4. `python -m sidereal --help` lists new commands.

---

## Tests (required)

Add/extend tests for:

1. Seed 3 generator counts, all ready, no “not yet authored”, Ophiuchus sign_on_house present
2. Seed files deterministic check includes seed_3
3. Store import: ready count matches formula; idempotent re-import
4. Tropical map: 0° → Aries, 30° → Taurus; no ophiuchus
5. Compare mode: 2000-01-01 12:00 UTC Sun Midpoint ≠ tropical labels (Sagittarius vs Capricorn)
6. Save → list → show round-trip
7. Existing 108 tests still pass (or updated counts only where intentional)

---

## Docs

Update:

- `README.md` — Seed 3 table, compare flag, save/list/show, ephe note
- `CLAUDE.md` — Phase 3 defaults
- `IMPLEMENTATION_NOTES.md` — only if you make a non-obvious frame/compare decision
- Do **not** rewrite `SPEC.md` wholesale; add a short “Phase 3 status” note at top or under §10 if useful

---

## Acceptance checklist

- [ ] `pytest` green
- [ ] `db import` → ready ≥ 437 (or ≥ 476 with stretch)
- [ ] Sample chart report shows non-stub `planet_in_house` + `sign_on_house` text
- [ ] `--compare tropical` emits comparison section without claiming one system is “correct”
- [ ] `save` / `list` / `show` work offline
- [ ] No `.se1`, `.db`, `charts/*`, `reports/*` committed
- [ ] Commit on `main` with a clear message (repo is already a standalone git repo in `sidereal/`)

---

## Suggested implementation order

1. Seed 3 schema + generator + regenerate JSON + inventory tests
2. Tropical ZodiacMap + compare wiring + tests
3. Save/list/show/interpret CLI
4. README/CLAUDE
5. Full pytest + manual smoke:

```bash
python -m sidereal db init --db data/sidereal.db
python -m sidereal db import --db data/sidereal.db
python -m sidereal db gaps --db data/sidereal.db
python -m sidereal chart \
  --date 2000-12-12 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --compare tropical \
  --db data/sidereal.db \
  --md /tmp/p3.md --out /tmp/p3.json
python -m sidereal save --label "OphiuchusSun" \
  --date 2000-12-12 --time 12:00 --tz UTC --lat 0 --lon 0
python -m sidereal list
```

---

## Definition of done

Phase 3 complete when personal charts produce **substantive** house/sign-on-house readings (not mostly stubs), can **compare tropical vs Midpoint** honestly, and can **save/reload** charts offline — with tests green and docs updated.

Start implementing now. Prefer correctness and complete Seed 3 over decorative CLI.
