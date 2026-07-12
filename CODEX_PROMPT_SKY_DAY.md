# Codex prompt — Public sky-day API (Parcel M)

Copy everything below the line into Codex.  
**Working directory:** `/mnt/c/Users/rober/Downloads/Projects/sidereal`

---

## Mission

Implement a **public, natal-free** sky geometry endpoint for Moon Chorus:

```text
GET /api/sky-day
```

Compute (or return cached) **today’s** Midpoint planetary longitudes for the game sphere. Cache **once per calendar day** per timezone. No birth data. No personal transits. Suitable for **Railway** deployment later.

Be **literal**. Follow the plan. Prefer reusing existing ephemeris / skypack glyph helpers.

## Required reading (first)

1. **Plan (source of truth):**  
   `/mnt/c/Users/rober/Downloads/Projects/aim-dojo/SPEC_PUBLIC_SKY_DAY.md`  
   Read §0–3, §5 Parcel M, §6–7. **Plan wins.**

2. Existing code to reuse:
   - `src/sidereal/skypack.py` (glyphs, mover shaping — do **not** require natal)
   - `src/sidereal/chart.py` / `ephemeris.py` / `config.py`
   - `src/sidereal/web/app.py` (routing, CORS patterns from sky-listen)
   - `src/sidereal/cli.py`

## Scope — Parcel M

| ID | Deliverable |
|----|-------------|
| M1 | `build_skyday(...)` (new module e.g. `src/sidereal/skyday.py` or clear section in skypack) |
| M2 | In-process (and optional file) cache keyed by `tz` + civil `date` |
| M3 | `GET /api/sky-day` with CORS for game origins |
| M4 | CLI: `python -m sidereal sky-day [-o out.json] [--tz] [--date]` |
| M5 | Tests + README section (curl + Railway env bullets) |
| M6 | **No aim-dojo edits** in this parcel |

## Out of scope

- Natal charts, skypack personal fields, sky-listen essays  
- Supabase / auth  
- Game glossary JSON (Parcel N)  
- Changing Midpoint boundary math  

## API contract (implement exactly)

### Request

```text
GET /api/sky-day?tz=UTC&date=YYYY-MM-DD&when=optional
```

- `tz`: optional IANA, default `UTC`  
- `date`: optional civil date in that tz; default = today in `tz`  
- `when`: optional; if omitted, use **local noon** of `date` in `tz` as the computation moment (document this)

### Response JSON

```json
{
  "schema_version": 1,
  "type": "skyday",
  "projection": "ecliptic_band_v2",
  "system": "midpoint_v1",
  "privacy": "public",
  "cache_date": "2026-07-12",
  "timezone": "UTC",
  "epoch_utc": "...",
  "generated_at": "...",
  "sign_band": [],
  "movers": [],
  "natal_ghosts": [],
  "resonances": [],
  "same_body_delta": [],
  "resonance_rank": []
}
```

**Must:**

- `type === "skyday"`  
- `privacy === "public"`  
- Empty arrays for all natal/relationship fields  
- Movers: sun, moon, mercury, venus, mars, jupiter, saturn, uranus, neptune, pluto, north_node, south_node (if ephemeris supports; document any omission)  
- Each mover: `id`, `name`, `glyph`, `lon_j2000`, `sign`, `degree_in_sign`, `kind`, `retro` (bool)

**Must not:**

- Include `natal_id`  
- Load or accept a natal chart for this route  

### Cache

```text
key = f"{tz}:{cache_date}"
```

- First miss: compute + store  
- Hit: return same payload (same `generated_at` / movers)  
- File cache under e.g. `data/cache/skyday/` optional but nice for Railway restarts; memory cache minimum  
- Tests must prove same-day second call does not change geometry (mock time or inspect cache)

### CORS

Allow at least:

- `http://127.0.0.1:8931`  
- `http://localhost:8931`  
- `https://aim-dojo.vercel.app`  

Plus env `SKY_DAY_CORS_ORIGINS` comma-list merge.  
Apply to `/api/sky-day` (OPTIONS + GET). Prefer not opening all routes unless already global.

### CLI

```bash
python -m sidereal sky-day --tz UTC --date 2026-07-12 -o /tmp/skyday.json
```

Exit 0; JSON validates as above.

### Errors

- 400 on bad tz/date/when  
- 500 on ephemeris failure with clear message  

## Implementation guidelines

1. **Do not** call `build_skypack` with a fake natal — build movers from a single computed chart at the day moment.  
2. Reuse glyph tables from skypack to avoid drift.  
3. `sign_band` from existing Midpoint boundary data (same as skypack).  
4. Thread-safe enough cache for multi-worker is best-effort; document process-local cache.  
5. Match project style: type hints, tests next to `tests/test_web_api.py` or `tests/test_skyday.py`.  
6. README: curl example + Railway bullets (`PORT`, `0.0.0.0`, ephe path, CORS env).

## Tests (required)

1. Response type/privacy/empty natal arrays  
2. Movers length ≥ 10; finite longitudes; glyphs present  
3. Cache stability same `tz`+`date`  
4. Different `date` → different `cache_date` / geometry change plausible  
5. CORS allow origin header for Vercel host  
6. CLI smoke write file  

```bash
pytest tests/test_skyday.py tests/test_web_api.py -q -k "sky_day or skyday" 
# or full suite if quick
```

## Definition of done

- [ ] M1–M6 complete per SPEC  
- [ ] pytest green for new tests  
- [ ] Sample curl output in completion summary  
- [ ] No aim-dojo changes  
- [ ] No personal natal leakage in response  

**Begin:** read `SPEC_PUBLIC_SKY_DAY.md` §3, then implement `build_skyday` + cache.
