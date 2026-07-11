# Codex prompt — skypack_v1 (Parcel A)

Copy everything below the line into Codex. Working directory must be the **sidereal** repo.

---

## Mission

Implement **Parcel A** of the Personal Planetarium plan: a local **`skypack_v1`** JSON export so Moon Chorus can render a real-time aesthetic sky + natal/transit glyphs.

You are the **source-of-truth** agent. Be literal. Follow the plan. Do not invent gameplay features.

## Required reading (do this first)

1. **Plan (source of truth):**  
   `/mnt/c/Users/rober/Downloads/Projects/aim-dojo/SPEC_PERSONAL_PLANETARIUM.md`  
   Read sections **1–4, 6–7 (Parcel A), 9 (sidereal anchors), 10**.  
   If anything conflicts with this prompt, **the plan wins**.

2. Existing code you will reuse (do not reimplement ephemeris):
   - `src/sidereal/chart.py` — natal points, `lon_j2000`, signs
   - `src/sidereal/transit.py` / aspect helpers — transit→natal geometry
   - `src/sidereal/library.py` — load saved charts by id
   - `src/sidereal/web/app.py` — API style for new route
   - `src/sidereal/cli.py` — CLI registration style
   - Saved natal example: `charts/bobby-19831129T132400Z-e1d0a0c471.json`

## Scope — you own only

| ID | Deliverable |
|----|-------------|
| A1 | Builder module producing `skypack_v1` dict/JSON |
| A2 | CLI: `python -m sidereal skypack …` |
| A3 | `GET /api/skypack` on the local FastAPI app |
| A4 | Checked-in fixture from bobby + **fixed** epoch |
| A5 | Short README usage blurb |

## Out of scope — do not touch

- Any file under `aim-dojo/`
- Interpretation essays / seed text inside skypack (geometry + glyphs only)
- Difficulty, weather, or game hooks
- Synastry / multiplayer packs
- Changing Midpoint boundary math or Swiss Ephemeris wiring except to **call** existing APIs
- Committing personal secrets beyond the already-local bobby chart pattern

## Hard requirements (checklist)

### Schema (plan §4) — implement exactly

- Top-level: `schema_version: 1`, `type: "skypack"`, `projection: "ecliptic_dome_v1"`
- Fields: `generated_at`, `epoch_utc`, `timezone`, `location`, `natal_id`, `natal_label`, `system: "midpoint_v1"`, `privacy: "local_only"`
- Arrays: `sign_band`, `movers`, `natal_ghosts`, `resonances`
- Body glyphs: ☉ ☽ ☿ ♀ ♂ ♃ ♄ ♅ ♆ ♇ and nodes ☊ ☋
- Aspect glyphs: ☌ ☍ △ □ ⚹ mapped from aspect ids  
  `conjunction` `opposition` `trine` `square` `sextile`
- Longitudes in degrees `[0, 360)` finite
- **No** markdown essays, **no** placement prose paragraphs, **no** house-on-floor data required for v1 (omit houses from pack unless already trivial; prefer omit)

### Builder behavior

1. Load natal chart by id from charts dir (same as other CLI commands).
2. Compute sky at `epoch` (default: now in given tz, or explicit `--when`).
3. `movers` = transit bodies at epoch (same body set the transit engine uses for sky).
4. `natal_ghosts` = natal body longitudes (fixed).
5. `resonances` = major transit→natal aspects within existing orb rules (reuse transit aspect code paths; do not invent new orbs).
6. `sign_band` = Midpoint 13 sign arcs from the project’s boundary data (same system as charts).

### CLI contract

```text
python -m sidereal skypack --natal <chart_id>
    [--when ISO_LOCAL]
    [--tz IANA]
    [--charts-dir charts]
    [--db data/sidereal.db]     # only if needed for consistency with other cmds; pack itself is geometry
    [--ephe-path data/ephe]
    [-o path.json]
```

- Default stdout or `-o` file = pretty-printed JSON, UTF-8.
- Nonzero exit on missing natal / bad time / ephemeris failure.
- Mirror flags style of existing `transit` / `chart` commands where possible.

### API contract

```text
GET /api/skypack?natal_id=<id>&when=<optional>&tz=<optional>
```

- 200 + skypack JSON
- 404 if natal missing
- 400 on bad parameters
- Localhost / existing host guard only — do not weaken security middleware

### Fixture (A4)

- Path: `data/fixtures/skypack_bobby_sample.json`
- Natal: bobby chart id already in `charts/`
- Fixed epoch (document in JSON `epoch_utc`): use **`2026-07-11T18:09:00+00:00`** (matches “bobby today's sky” conversation era) unless ephemeris requires local; then pick one fixed instant and put it in `epoch_utc` + comment in test docstring
- Must validate against the same schema checks as unit tests

### Tests (required)

Add `tests/test_skypack.py` (or split if project style demands) covering:

1. Schema keys present; `schema_version == 1`
2. Every mover/ghost has `glyph`, finite `lon_j2000` in range
3. Every resonance has valid `aspect_id` + `aspect_glyph`
4. Round-trip: build → `json.dumps` → `json.loads` → required keys
5. CLI smoke: invoke skypack for bobby → exit 0 (use tmp path)
6. Optional: API test following patterns in `tests/test_web_api.py`

Run:

```bash
cd /mnt/c/Users/rober/Downloads/Projects/sidereal
. .venv/bin/activate
pytest tests/test_skypack.py -q
# and full suite if quick enough
pytest -q
```

### README (A5)

Add a short subsection, e.g. “Sky pack for Moon Chorus”, with:

```bash
python -m sidereal skypack --natal bobby-19831129T132400Z-e1d0a0c471 \
  -o data/fixtures/skypack_bobby_sample.json
```

and note: local only; consumed by aim-dojo `?sky=clocked_chart`.

## Implementation guidelines (Codex-style)

1. **Small pure module** preferred: e.g. `src/sidereal/skypack.py` with `build_skypack(...)` returning a `dict` or frozen dataclass + `to_dict()`.
2. **Reuse** transit/chart computation; do not copy Swiss Ephemeris calls ad hoc.
3. Centralize glyph maps in one dict (planets + aspects + signs).
4. Validate inputs the same way other library/CLI entrypoints do (Path expanduser, clear errors).
5. Match existing code style: type hints, frozen dataclasses where the project already uses them, no unnecessary deps.
6. Do not reformat unrelated files.
7. After implementation, print: files changed, how to regenerate fixture, sample `curl` for `/api/skypack`.

## Definition of done

- [ ] A1–A5 complete per plan §7 Parcel A
- [ ] `pytest tests/test_skypack.py` green
- [ ] Fixture committed and loads
- [ ] No aim-dojo edits
- [ ] Plan §4 schema honored field-for-field

## When stuck

- Prefer thinner pack over new features.
- If sign boundary export is awkward, emit `sign_band` from existing Midpoint boundary JSON already in `data/boundaries/`.
- If API tests are heavy, ship CLI + unit tests first, then API.

**Begin:** read the plan file, then implement A1.
