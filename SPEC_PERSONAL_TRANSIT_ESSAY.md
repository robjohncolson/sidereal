# Personal transit essay (Parcel T)

**Status:** planned
**Depends on:** Parcel P (auth + natal + skypack), Parcel Q (DeepSeek client patterns), aim-dojo Save my sky (JWT session)
**Repos:** sidereal (Railway) · aim-dojo (Vercel) · DeepSeek (async author) · optional Codex offline modeling

## Product intent

When a signed-in user with a saved chart starts a play session, the server builds a **full transit-to-natal study for “now”** (all major contacts in the study pipeline—not only glyphs currently pickable on the sphere). That structured study is handed to a model as **facts only**. The model returns one short **symbolic study essay**—the treat a player could approximate by Listen-poking every body, synthesized into a single reading.

Generation is **async**. At session start the essay is usually not ready. When it becomes ready, the game shows a **toast / soft notification**. The user opens **pause** and taps **TODAY’S SKY NOTE** (or similar) to read it. Play is never blocked.

## Why this is different from Parcel Q

| | Shared seeds (Q/S) | Personal essay (T) |
|--|--------------------|--------------------|
| Key | interpretation id | `user_id` + civil day + natal fingerprint |
| Audience | everyone | one user |
| Input | catalog id + keywords | **full transit geometry summary** |
| Storage | SQLite catalog | private row (memory/disk/SQLite/Supabase JSON) |
| UX | improves Listen cards | toast + pause reader |

Geometry remains ephemeris-only. The model never invents longitudes or aspects.

## Goals

1. **Full synthesis** — essay input includes the complete major transit set for the study (orbs, applying/separating, same-body deltas, luminaries, outers), not only on-screen picks.
2. **Async treat** — enqueue at session open / first personal load; poll or light GET for status.
3. **Pause reader** — dedicated pause UI; no mid-combat modal that steals aim.
4. **DeepSeek online** — same server-key pattern as Q; Codex used to **model** prompt/shape offline.
5. **Epistemic safety** — symbolic study; ban medical/financial/fate/guaranteed-outcome language; no compatibility scores.
6. **Privacy** — essay never enters leaderboard, share URL, or public sky-day.

## Non-goals (v1)

- Live multiplayer / synastry essays
- Replacing Listen poke cards
- Multi-day essay history UI (store may keep last N days server-side)
- Forcing essay before PLAY or training
- LLM-derived geometry

## UX (aim-dojo)

### Session start (clocked / personal, signed in + has chart)

1. After personal skypack link (or parallel to it), client calls
   `POST /api/me/transit-essay` or `POST /api/me/transit-essay/enqueue`
   (idempotent for the civil day).
2. Response: `{ "status": "pending"|"ready"|"failed", "essay_id": "…", "cache_date": "YYYY-MM-DD" }`.
3. If `pending`, client polls `GET /api/me/transit-essay` every ~8–15s (backoff, max ~2–3 min).
4. On first transition to `ready`:
   - `showGhostToast` e.g. `SKY NOTE READY`
   - set pause badge / pulse on the essay button
5. Pause settings: button **TODAY’S SKY NOTE** (disabled while pending; opens scrollable panel when ready).
6. Guest / no chart: no enqueue; button hidden or “save your sky first”.

### Reader panel (pause only)

- Title + short meta: cache date, epistemic footer
- Body: markdown-ish plain text or simple paragraphs (no HTML from model)
- Optional sections if model returns structured fields: `headline`, `body`, `watchpoints[]`
- Close returns to pause; never auto-opens during combat

## Server design (sidereal)

### Fact payload (built before any model call)

From existing transit pipeline (`calculate_transit_study` / geometry):

```json
{
  "schema_version": 1,
  "type": "transit_essay_facts",
  "cache_date": "2026-07-12",
  "timezone": "America/New_York",
  "epoch_utc": "…",
  "natal": {
    "time_unknown": false,
    "tz": "…",
    "placements": [ { "body": "sun", "sign": "scorpio", "degree_in_sign": 5.7 } ]
  },
  "sky": {
    "movers": [ { "body": "mars", "sign": "leo", "retro": false } ]
  },
  "same_body_delta": [ { "body": "sun", "delta_deg": 12.3 } ],
  "aspects": [
    {
      "transit_body": "mars",
      "natal_point": "moon",
      "aspect_id": "square",
      "orb": 0.8,
      "applying": true,
      "seed_status": "ready",
      "seed_summary": "optional short catalog line if ready"
    }
  ]
}
```

Rules:

- Include **all** major aspects in the study’s orb policy (same as desk transit report), ranked by orb/tightness.
- Cap list length for the model (e.g. top 24 by orb) but **do not** filter by “visible on sphere”.
- Optional: attach catalog `summary` snippets for ready seeds only (shared library), never birth raw fields beyond placements already in facts.
- **Never** send API keys, email, or Supabase tokens to the model.

### Essay record

```json
{
  "schema_version": 1,
  "type": "personal_transit_essay",
  "status": "ready",
  "cache_date": "2026-07-12",
  "headline": "…",
  "body": "…",
  "watchpoints": ["…"],
  "epistemic": "symbolic study notes, not predictions",
  "model": "deepseek-v4-flash",
  "source": "ai-deepseek",
  "generated_at": "…"
}
```

### Endpoints

| Method | Path | Behavior |
|--------|------|----------|
| `POST` | `/api/me/transit-essay` | Idempotent enqueue for today; return current status |
| `GET` | `/api/me/transit-essay` | Current day’s essay or `{status: pending\|none\|failed}` |
| `DELETE` | `/api/me/transit-essay` | Optional: clear cached essay for today (debug/owner) |

Auth: same JWT as `/api/me/*`. CORS: same personal origins.

### Async worker

- Reuse Q’s pattern: in-process queue, de-dupe by `(user_id, cache_date)`.
- Missing `DEEPSEEK_API_KEY`: enqueue no-ops; GET returns `status: unavailable`.
- Timeouts and failed validation → `status: failed` with generic client message (no raw provider errors).
- Cache on success until civil date rolls in user tz (or UTC if time_unknown / tz policy matches skypack).

### Prompt (DeepSeek / Codex model)

**System:** Sidereal Midpoint 13-sign symbolic study; Ophiuchus first-class; no medical/financial/legal/fate guarantees; synthesize the fact list into one coherent note a careful student could piece together by examining all contacts; do not invent aspects not in the facts; return JSON `{headline, body, watchpoints}`.

**User:** the fact payload only (plus optional ready seed snippets).

**Offline modeling:** Codex can produce sample essays from exported fact JSON (CLI below) without production keys.

### CLI (optional but useful)

```bash
python -m sidereal transit-essay dry-run --natal … --when …   # print facts + prompt, no network
python -m sidereal transit-essay apply-json --file sample.json  # validate shape only
```

## aim-dojo client

| Piece | Behavior |
|-------|----------|
| Enqueue | After personal chart linked / on pause init if chart present |
| Poll | While `pending` and tab visible; stop on ready/failed/timeout |
| Toast | Once per ready transition per session |
| Pause button | `TODAY’S SKY NOTE` under SAVE MY SKY or settings |
| Reader | Scrollable pause overlay; Esc still pause-only |

No essay text in share URLs, leaderboard rows, or realtime presence.

## Privacy & safety

- Birth profile stays Supabase natal; essay storage is private to `user_id`.
- Do not log full essay + birth together in plaintext logs.
- Rate limit: 1 successful generation per user per civil day (v1); re-enqueue only if natal profile changed (fingerprint).
- Epistemic footer always shown in reader.

## Acceptance

### API
- [ ] Enqueue without natal → 404
- [ ] Enqueue with natal → pending then ready (mocked model in tests)
- [ ] Fact payload includes multiple aspects beyond a single body
- [ ] Model output validated; banned fragments rejected → failed
- [ ] Second POST same day returns cached ready without second model call

### Client
- [ ] Guest: no enqueue spam
- [ ] Toast only once when ready
- [ ] Pause button opens reader with full body
- [ ] Combat never blocked

### Ops
- [ ] DeepSeek key server-only
- [ ] Document poll interval and day-cache policy in README / RAILWAY.md

## Parcel split

| Parcel | Repo | Deliverable |
|--------|------|-------------|
| **T1** | sidereal | Facts builder, storage, enqueue, GET/POST, DeepSeek author, tests (mock) |
| **T2** | aim-dojo | Enqueue, poll, toast, pause button + reader |
| **T3** | ops | Enable key; smoke one real essay |

**Order:** T1 → T2 (T2 can stub against T1 shapes). Codex models prompts offline anytime.

## Open choices (defaults)

| Choice | Default |
|--------|---------|
| Civil day tz | User natal `tz` if known, else device tz on request |
| Max aspects in facts | 24 tightest major aspects |
| Essay length | headline ≤120 chars; body ~400–1200 chars; ≤5 watchpoints |
| Model | `deepseek-v4-flash` (same as Q) |
| Storage | Process cache + optional SQLite table `personal_transit_essays` on `SIDEREAL_DB` volume |

## Relationship to poking the sky

Listen cards remain **local drills** (one body / sign).
The essay is the **whole-map synthesis**—everything the transit study knows for today, in one readable treat when the worker finishes.
