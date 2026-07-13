# Codex prompt — Personal transit essay API (Parcel T1)

Copy everything below the line into Codex.
**Working directory:** `/mnt/c/Users/rober/Downloads/Projects/sidereal`

---

## Mission

Implement **async personal transit essays**: for an authenticated user with a saved natal profile, build a **full transit-to-natal fact payload for now** (all major study aspects, not sphere-visibility filtered), enqueue a DeepSeek completion that returns a short symbolic synthesis, and serve status/result over `/api/me/transit-essay`.

Be **literal**. Geometry from ephemeris only. Never block game-critical handlers on the model call. Never put `DEEPSEEK_API_KEY` in responses or logs.

## Required reading (first)

1. **Spec (wins):** `SPEC_PERSONAL_TRANSIT_ESSAY.md`
2. Parcel P: natal store, `/api/me/*`, JWT auth in `web/app.py`
3. Transit study: `interpret/transit.py`, `sky_listen.py` personal block, `skypack` personal path
4. Parcel Q patterns: `interpret/ai_seed.py` DeepSeek client, queue de-dupe, banned-phrase style validation

## Scope — Parcel T1 (this PR, sidereal only)

| ID | Task |
|----|------|
| T1 | `build_transit_essay_facts(record, when=…)` → JSON facts (placements, movers, same_body_delta, aspects up to cap) |
| T2 | Essay store (memory + optional SQLite on `SIDEREAL_DB`) keyed by user_id + cache_date + natal fingerprint |
| T3 | DeepSeek author: facts → validated `{headline, body, watchpoints[]}` |
| T4 | In-process queue; de-dupe; no-op if no API key |
| T5 | `POST /api/me/transit-essay` enqueue/idempotent; `GET /api/me/transit-essay` status/body |
| T6 | CORS/private headers like other `/api/me/*` |
| T7 | Tests with mocked transport; no live DeepSeek in CI |
| T8 | README + RAILWAY note (env already has DEEPSEEK_*) |

## Out of scope

- aim-dojo UI (Parcel T2 — separate prompt)
- Changing shared seed catalog
- Synastry essays

## API shapes

**GET pending:**

```json
{ "schema_version": 1, "type": "personal_transit_essay", "status": "pending", "cache_date": "2026-07-12" }
```

**GET ready:** include `headline`, `body`, `watchpoints`, `epistemic`, `generated_at`.

**POST:** same body as GET current state after ensuring job exists.

## Epistemic

- Symbolic Midpoint 13-sign language; Ophiuchus first-class
- Reject banned predictive/medical/financial fragments (reuse or mirror Q lists)
- Model must not invent aspects missing from facts

## Verification

```bash
pytest tests/test_transit_essay*.py -q
# manual with key:
# POST /api/me/transit-essay with Bearer → pending → GET until ready
```

## Checklist

- [ ] T1–T8
- [ ] pytest green
- [ ] No aim-dojo edits
- [ ] Facts include multi-body aspects (not single Listen highlight set)
