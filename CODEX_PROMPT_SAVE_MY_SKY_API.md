# Codex prompt — Save my sky API (Parcel P)

Copy everything below the line into Codex.
**Working directory:** `/mnt/c/Users/rober/Downloads/Projects/sidereal`

---

## Mission

Implement the **authenticated personal natal + daily skypack** API for Moon Chorus on Railway, per the program spec. Users who Save my sky get transit geometry and Listen personal blocks; public sky-day stays natal-free.

Be **literal**. Prefer interfaces so Supabase can be swapped with a file/dev backend for tests.

## Required reading (first)

1. **Program plan:**
   `/mnt/c/Users/rober/Downloads/Projects/aim-dojo/SPEC_PUBLIC_TRANSITS_AND_AI_SEEDS.md`
   §§0–5, §8–10. **Plan wins.**

2. Existing code: `skypack.py`, `skyday.py`, `sky_listen.py`, `web/app.py`, `chart.py`, `library.py`, JWT/CORS patterns.

## Scope — Parcel P

| ID | Task |
|----|------|
| P1 | `NatalRecord` / `NatalStore` protocol (get/upsert/delete by `user_id`) |
| P2 | Dev store: JSON file or memory for tests; optional Supabase store behind env |
| P3 | `POST/GET/DELETE /api/me/natal` with Bearer JWT validation (Supabase JWT secret/JWKS) |
| P4 | `GET /api/me/skypack` — personal skypack for today (day cache per user) |
| P5 | Extend `sky-listen` so JWT user natal drives personal block when `natal_id` omitted |
| P6 | CORS for Vercel on new routes; no birth fields on unrelated endpoints |
| P7 | Tests with mocked JWT + memory natal store; README env section |

## Out of scope

- DeepSeek / AI fill (Parcel Q)
- aim-dojo UI (Parcel R)
- Leaderboard changes
- Real multi-tenant admin UI

## Auth

- Header: `Authorization: Bearer <supabase_access_token>`
- Env: `SUPABASE_URL`, `SUPABASE_JWT_SECRET` (or JWKS URL)
- Invalid/missing token → 401 on `/api/me/*`
- Tests: inject a test auth dependency that sets `user_id` without real Supabase

If full JWT verify is too heavy for first cut: implement **`NatalStore` + routes + `X-Dev-User-Id` only when `SIDEREAL_DEV_AUTH=1`**, plus a clear JWT TODO — but **prefer working JWT HS256 verify** with secret (standard Supabase).

## Natal upsert body

```json
{
  "birth_date": "1983-11-29",
  "birth_time": "22:24:00",
  "time_unknown": false,
  "tz": "Asia/Tokyo",
  "lat": 35.68,
  "lon": 139.69,
  "place_label": "Tokyo, Japan"
}
```

- `time_unknown` or null time → compute with local noon; set flag in stored metadata
- Validate tz/date; lat/lon optional but recommended

## Skypack response

- Reuse `build_skypack` / equivalent from computed natal + now
- `privacy`: `user_private`
- Day cache key: `{user_id}:{tz}:{cache_date}`
- Empty chart dir OK on Railway

## sky-listen

- If Bearer valid and body/sign provided: personal block from that user’s natal
- If `natal_id` query still used for local file charts: keep backward compatible
- On stub/missing seeds: still return geometry + stub text; optional hook point `enqueue_ai_seed(id)` no-op if Q not merged

## Tests

- Unauthorized me/* → 401
- Upsert + get natal
- Skypack has movers + natal_ghosts non-empty
- sky-listen personal.available true with JWT
- No regression on public `/api/sky-day`

## Definition of done

- [ ] P1–P7
- [ ] pytest green
- [ ] Sample curl (with fake/dev auth) in README
- [ ] No aim-dojo edits

**Begin:** read program SPEC §§3–5, implement `NatalStore` + memory backend + routes.
