# Sky Temple Chat — DeepSeek dialogue (Parcel C)

**Canonical product + API spec.** UI details also live in aim-dojo; this file wins for server behavior.

**Status:** planned  
**Version:** 1.0 · 2026-07-13  
**Repos:** sidereal (Railway API + DeepSeek) · aim-dojo (Vercel temple UI)  
**Depends on:** Save my sky auth + natal, transit essay facts path, Sky Temple focus HUD  
**Sibling:** personal transit essay (one-shot day monologue) · sky brief (external paste)

---

## 0. Product intent

While in **Sky Temple**, the player can **ask a short question** about the focused transit, natal ghost, aspect, or the open sky. The server builds a **focus-scoped fact packet** from ephemeris geometry (never invents contacts), hands it to DeepSeek with the user’s message + day thread, and returns a **short symbolic reply**.

This is **not** combat chat, not multiplayer, and not a free-form life coach. It is a **temple study dialogue** grounded in the same rails as Listen / essay / brief.

### Locked decisions (v1)

| Choice | Lock |
|--------|------|
| Surface | **Temple-only** (composer while `templeActive`; restore with temple after pause) |
| Thread scope | **One civil-day thread per user** (`user_id` + `cache_date` + natal fingerprint) |
| Focus | **Attached per turn** (each message carries current focus; model sees focus + nearby facts) |
| Latency | **Async-capable** with optimistic “listening…”; poll until ready (essay-style reliability) |
| Auth | **Bearer JWT + saved natal required** for personal chat |
| Public / guest | **No chat** in v1 (hide control; no enqueue spam) |

---

## 1. Goals

1. Temple focus → ask → short grounded reply without leaving the investigation loop.  
2. Reuse DeepSeek transport, banned-phrase validation, and JWT patterns from transit essay / seed worker.  
3. Facts-only geometry; model must not invent aspects or placements.  
4. Day-scoped private thread; rate-limited.  
5. Combat never blocked; no chat chrome in dojo or on leaderboard/share/realtime.  
6. Epistemic footer always present; symbolic study only.

---

## 2. Non-goals (v1)

- Voice / TTS  
- Multiplayer or presence chat  
- Synastry / multi-chart dialogue  
- Guest or public-only DeepSeek  
- Replacing TODAY’S SKY NOTE essay or sky brief paste  
- Streaming tokens to the client (single reply objects are enough)  
- Long multi-page answers  
- Free chat with no focus and no fact packet  
- Putting Hoʻoponopono phrases or ritual speech into the model  

---

## 3. UX (aim-dojo)

### 3.1 Entry

Preconditions: `templeActive`, signed in, chart linked (`_personalListenExpected` / has natal).

| Control | Behavior |
|---------|----------|
| **T** key (not typing in forms) | Open composer (temporary pointer unlock) |
| Panel button **ASK THE SKY** | Same |
| Pause while temple-resume wanted | Composer closed; on temple restore, thread still available |

Dojo / no chart / guest: no **T** binding for chat; no button.

### 3.2 Composer + thread

```
┌─ SKY TEMPLE panel ─────────────────────┐
│ title / meta (focus)                     │
│ study body (glossary + personal desk)    │
│ ── dialogue ──                           │
│ [prior turns, scroll]                    │
│ [listening…] while pending               │
│ ┌──────────────────────────┐ [SEND]      │
│ │ ask about this focus…    │             │
│ └──────────────────────────┘             │
│ epistemic · T opens · Esc closes ask     │
└──────────────────────────────────────────┘
```

- **Enter** sends (Shift+Enter = newline if multi-line).  
- **Esc** closes composer only (stays in temple).  
- Empty focus: still allow chat with focus `kind: "sky"` (whole-day movers + top aspects, tighter fact cap).  
- Max message length: **500** characters client-side; server rejects > **800**.  
- Show last **N = 12** turns in UI; server may keep more for the day.

### 3.3 Optimistic UX

1. User sends → append local user turn immediately.  
2. Show assistant placeholder: `listening…`  
3. `POST /api/me/sky-chat` → `{ status, thread_id, turn_id }`  
4. If `ready`, paint reply; if `pending`, poll `GET /api/me/sky-chat?thread_id=…` every **2–4s** (backoff, max ~90s).  
5. On `failed`, show soft error: `sky notes unavailable` (no raw provider text).

### 3.4 Pause / tab-switch

- Temple pause resume (existing `_templeResumeWanted`) **preserves** thread_id in client memory for the session.  
- Do **not** clear day thread on pause.  
- On full run reset / sign-out: clear local thread UI state; server day cache remains until date rolls.

### 3.5 Pointer lock

- Opening composer: `document.exitPointerLock()` + flag `_templeChatOpen`.  
- Closing composer / after send optional: restore lock on next canvas click (same pattern as post-Esc temple relock).  
- While composer open: WASD/fire must not drive combat (already true if templeActive).

---

## 4. Focus payload (client → server)

```json
{
  "kind": "body" | "sign" | "natal" | "aspect" | "sky",
  "body": "mars",
  "sign": "leo",
  "natal_point": "moon",
  "aspect_id": "square",
  "label": "optional display only — server ignores for geometry"
}
```

| kind | Required fields |
|------|-----------------|
| `body` | `body` (transit mover id) |
| `sign` | `sign` (midpoint sign id) |
| `natal` | `natal_point` |
| `aspect` | `body` (transit), `natal_point`, `aspect_id` |
| `sky` | none |

Server **recomputes** all longitudes/orbs from natal + ephemeris at `when`. Client labels are display-only; never trusted for geometry.

---

## 5. API (sidereal)

Auth: same Bearer JWT as `/api/me/*`.  
CORS: same personal origins as essay / skypack.

### 5.1 POST `/api/me/sky-chat`

**Request:**

```json
{
  "message": "What is this square asking of me this week?",
  "focus": { "kind": "aspect", "body": "mars", "natal_point": "moon", "aspect_id": "square" },
  "thread_id": "optional-if-continuing",
  "when": "optional ISO",
  "tz": "optional IANA"
}
```

**Behavior:**

1. 401 without session; 404 without natal chart.  
2. Validate message (non-empty, max length, no control spam).  
3. Resolve civil `cache_date` (same policy as transit essay / natal tz).  
4. Load or create day thread for `(user_id, cache_date, natal_fingerprint)`.  
5. If `thread_id` provided and mismatches day thread → prefer: **ignore client thread_id if wrong date; always bind to day thread**.  
6. Build **focus facts** (below).  
7. Append user turn; enqueue model job (de-dupe by `turn_id`).  
8. Return current thread status (may already be ready if worker is fast / sync path).

**Response (common envelope):**

```json
{
  "schema_version": 1,
  "type": "sky_chat",
  "status": "pending" | "ready" | "failed" | "unavailable",
  "thread_id": "…",
  "cache_date": "2026-07-13",
  "turn_id": "…",
  "focus": { "kind": "aspect", "body": "mars", "natal_point": "moon", "aspect_id": "square" },
  "turns": [
    { "role": "user", "text": "…", "focus": { }, "at": "…" },
    { "role": "assistant", "text": "…", "at": "…", "status": "ready" }
  ],
  "epistemic": "Symbolic study notes, not predictions. Not medical, legal, or financial advice.",
  "remaining_turns": 7
}
```

`unavailable` when no `DEEPSEEK_API_KEY` (enqueue no-op, honest status).

### 5.2 GET `/api/me/sky-chat`

Query: optional `thread_id` (else today’s thread).

Returns same envelope; empty `turns` + `status: "none"` if no thread today.

### 5.3 DELETE `/api/me/sky-chat` (optional v1.1)

Clear today’s thread for the user (debug / user “clear dialogue”).

### 5.4 Rate limits (v1)

| Limit | Value |
|-------|-------|
| Successful assistant replies / civil day | **10** |
| Pending jobs / user | **1** (queue next after prior finishes) |
| Message max chars | **800** server |
| History sent to model | last **8** turns + current |
| Reply target length | **80–180 words** (prompt); hard reject if > ~600 words |

Exceed day cap → `429` with `{ "status": "limited", "remaining_turns": 0 }`.

---

## 6. Focus facts (server)

Built **before** any model call. Prefer reusing `build_transit_essay_facts` then **slice** by focus, or a dedicated `build_sky_chat_facts(record, focus, when=…)`.

### 6.1 Always include

```json
{
  "schema_version": 1,
  "type": "sky_chat_facts",
  "cache_date": "…",
  "timezone": "…",
  "epoch_utc": "…",
  "focus": { },
  "natal_placements_short": [ { "body": "moon", "sign": "…", "degree_in_sign": 0 } ],
  "movers_short": [ { "body": "mars", "sign": "…", "retro": false } ]
}
```

Omit raw `lat` / `lon` / email / user_id from the model payload.

### 6.2 By focus kind

| kind | Extra facts |
|------|-------------|
| `body` | Transit body placement; same-body delta if any; up to **6** tightest aspects involving that transit body |
| `natal` | Natal placement + house if known; up to **6** transit aspects to that natal point |
| `aspect` | That contact’s orb, applying/separating, both placements; **2–4** neighboring tight aspects for context |
| `sign` | Sign character seed if ready; movers currently in sign; natal bodies in sign |
| `sky` | Top **8** aspects by tightness; luminaries; no single-body essay dump of all 24 unless needed |

Optional: ready catalog `seed_summary` lines for aspect ids (shared seeds only).

### 6.3 Never in facts

- Birth lat/lon/place strings  
- API keys / tokens  
- Prior banned model text  
- Full essay body (optional one-line `day_headline` only if essay ready — not full essay paste in v1)

---

## 7. DeepSeek author

Reuse `DeepSeekClient` / config from `interpret/ai_seed.py` (same env: `DEEPSEEK_API_KEY`, model, base URL, timeout).

### 7.1 System prompt (spirit)

- Sidereal **Midpoint 13-sign**; Ophiuchus first-class  
- Symbolic study; **no** medical, legal, financial, fate guarantees, “you will…” outcomes  
- Answer **only** using provided facts + prior turns; if insufficient facts, say what is known and stop  
- Short reply: 80–180 words, plain language paragraphs  
- Return JSON: `{ "reply": "…" }` only  

### 7.2 User payload

```json
{
  "facts": { },
  "history": [ { "role": "user|assistant", "text": "…" } ],
  "message": "…"
}
```

### 7.3 Validation

- JSON object with non-empty `reply` string  
- Banned-phrase scan (reuse / mirror essay + seed lists)  
- Length cap  
- Failure → turn `status: failed`; thread remains usable for a later message  

---

## 8. Storage

Key: `(user_id, cache_date, natal_fingerprint)` → one `SkyChatThread`.

```json
{
  "thread_id": "uuid",
  "user_id": "…",
  "cache_date": "…",
  "natal_fingerprint": "…",
  "turns": [ ],
  "pending_turn_id": null,
  "success_count": 3
}
```

Memory store + optional SQLite on `SIDEREAL_DB` (same spirit as essay store). Private to user; never public sky-day.

---

## 9. Client map (aim-dojo)

| Piece | Location |
|-------|----------|
| API helpers | `save-my-sky.js` — `postSkyChat`, `getSkyChat` |
| Composer UI | temple panel section `#skyTempleChat` |
| Open/close | `T` / button; Esc closes composer |
| Poll | while pending + tab visible |
| Focus snapshot | from `_templeFocus` / `_skySel` → focus JSON |
| Privacy | never send chat to dojo POST, share URL, presence, leaderboard |

### 9.1 CFG

```js
skyChat: {
  enabled: true,
  openKey: 'KeyT',
  maxMessageChars: 500,
  pollMs: 3000,
  pollMaxMs: 90000,
}
```

---

## 10. Privacy & safety

| Rule | Detail |
|------|--------|
| Auth | JWT only |
| Chart | 404 pattern if no natal |
| Model input | facts + short history only |
| Model key | server-only |
| Surfaces | never leaderboard / share / realtime / guest |
| Logs | no full chat + birth coords together |
| Epistemic | fixed string on every GET/POST ready body |

---

## 11. Acceptance

### API
- [ ] No auth → 401  
- [ ] Auth, no natal → 404  
- [ ] Valid POST → pending or ready envelope with `thread_id`  
- [ ] Facts for aspect focus include that contact’s orb  
- [ ] Model invent path rejected (mock bad output → failed turn)  
- [ ] Day cap → 429 after 10 successes  
- [ ] No key → `unavailable`  
- [ ] pytest green with mocked transport  

### Client
- [ ] Guest / no chart: no composer  
- [ ] Temple + chart: T opens composer  
- [ ] Send shows user line + listening… then reply  
- [ ] Pause/resume temple: thread still visible  
- [ ] Combat / dojo: no chat UI  
- [ ] Contract tests for CFG + no outbound leakage  

---

## 12. Phased delivery

| Phase | Repo | Ship |
|-------|------|------|
| **C1** | sidereal | Facts builder, thread store, DeepSeek author, POST/GET, rate limit, tests |
| **C2** | aim-dojo | Composer UI, T key, poll, focus snapshot, save-my-sky helpers |
| **C3** | both | DELETE clear thread; polish copy; optional day_headline from essay |

---

## 13. Summary

> **In the temple, ask the sky about what you are looking at.** DeepSeek answers from focus-scoped transit facts and a private day thread — short, symbolic, never combat, never invented geometry.
