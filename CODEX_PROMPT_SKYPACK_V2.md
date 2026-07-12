# Codex prompt — skypack v2 (Parcel C)

Copy everything below the line into Codex. Working directory: **sidereal** repo.

---

## Mission

Implement **Parcel C** of Personal Planetarium **v2**: extend `skypack` so the game can show **shortest-arc Δ (now vs natal same body)** and **tasteful any-hit resonance ranking**, with an honest projection id for the coherent sky.

You are **contract-first and literal**. Do not invent game UI. Do not edit aim-dojo.

## Required reading (first)

1. **Plan (source of truth):**  
   `/mnt/c/Users/rober/Downloads/Projects/aim-dojo/SPEC_PERSONAL_PLANETARIUM_V2.md`  
   Read §0–2, §6, §9–12 (Parcel C), acceptance related to pack.  
   **If conflict: the plan wins.**

2. Existing code:
   - `src/sidereal/skypack.py` (v1 builder)
   - `tests/test_skypack.py`
   - CLI `skypack` in `src/sidereal/cli.py`
   - `GET /api/skypack` in `src/sidereal/web/app.py`
   - Fixture `data/fixtures/skypack_bobby_sample.json`

## Scope — Parcel C only

| ID | Deliverable |
|----|-------------|
| C1 | Shortest-arc helper; `same_body_delta[]` on every build |
| C2 | `schema_version: 2`, `projection: "ecliptic_band_v2"` |
| C3 | `resonance_rank[]` optional but **do implement**: tightest-first sort of resonances |
| C4 | Regenerate bobby fixture (fixed epoch — keep prior fixture epoch if possible for continuity) |
| C5 | CLI/API unchanged in spirit; README blurb for v2 fields |
| C6 | **Keep all v1 arrays/fields** (`movers`, `natal_ghosts`, `resonances`, `sign_band`, glyphs, etc.) |

## Out of scope

- aim-dojo / constellation stick JSON
- Interpretation essays in pack
- Weather, difficulty, synastry packs
- Changing ephemeris/Midpoint astronomy formulas except to call them
- Removing v1 keys

## Hard requirements

### Shortest arc

```text
delta_deg = min( |lon_a - lon_b| mod 360,  360 - that )  →  range [0, 180]
```

Finite floats; reject non-finite inputs in helper with clear errors (match project style).

### `same_body_delta[]` entry

```json
{
  "id": "sun",
  "delta_deg": 137.09,
  "mover_lon_j2000": 109.0,
  "natal_lon_j2000": 247.0
}
```

- One row per body id present in **both** movers and natal_ghosts.
- `delta_deg` must equal shortest arc between the two lons (test with tolerance 1e-6 or 1e-4 deg).
- Include sun, moon, planets, nodes if both sides exist.

### `resonance_rank[]` entry

```json
{
  "transit_body": "pluto",
  "natal_point": "moon",
  "aspect_id": "trine",
  "aspect_glyph": "△",
  "orb": 0.32,
  "orb_limit": 8.0,
  "rank": 1
}
```

- Sort key: `orb / orb_limit` ascending (missing limit → treat carefully, document).
- Tie-break: `transit_body`, then `natal_point`, then `aspect_id` (stable, deterministic).
- `rank` is 1-based after sort.
- May include all resonances (client will cap at 8); do not silently drop unless orb invalid.

### Top-level

- `schema_version`: **2**
- `projection`: **`ecliptic_band_v2`**
- `type`: `skypack`
- `privacy`: `local_only` still for natal-bearing packs

### Fixture

```bash
python -m sidereal skypack \
  --natal bobby-19831129T132400Z-e1d0a0c471 \
  --when 2026-07-11T14:09:00 \
  --tz America/New_York \
  --ephe-path data/ephe \
  -o data/fixtures/skypack_bobby_sample.json
```

(Use the same when/tz as existing fixture unless tests force otherwise.)

### Tests (`tests/test_skypack.py` or extension)

1. Shortest-arc unit cases: 0°, 180°, wrap across 0° (e.g. 10 vs 350 → 20°), 90°.
2. Built pack `schema_version == 2`, projection string exact.
3. Every `same_body_delta` matches independent computation from movers/ghosts.
4. `resonance_rank` is sorted and ranks unique 1..n.
5. v1 keys still present (`movers`, `natal_ghosts`, `resonances`, `sign_band`).
6. CLI or builder smoke still green.
7. Full `pytest -q` if reasonable.

### README

Short note: v2 adds `same_body_delta` + `resonance_rank`; game uses theatre lighting but real longitudes.

## Implementation guidelines

1. Prefer pure functions in `skypack.py`; no new dependencies.
2. Do not reformat unrelated files.
3. Preserve existing CLI flags.
4. After done, print: files changed, how to regen fixture, sample JSON snippet of one delta + top rank row.

## Definition of done

- [ ] C1–C6 complete per plan §10 Parcel C  
- [ ] Fixture regenerated and committed in the worktree  
- [ ] Tests green  
- [ ] No aim-dojo edits  

**Begin:** read the v2 plan, then implement C1.
