# Codex prompt — Sky Chat API (Parcel C1)

Copy everything below the line into Codex.  
**Working directory:** `/mnt/c/Users/rober/Downloads/Projects/sidereal`

---

## Mission

Implement **Sky Temple Chat** server: authenticated, natal-required, **day-scoped private threads** where each user message is answered by DeepSeek from a **focus-scoped transit fact packet**. Endpoints:

- `POST /api/me/sky-chat`
- `GET /api/me/sky-chat`

**Spec wins:**  
`/mnt/c/Users/rober/Downloads/Projects/sidereal/SPEC_SKY_CHAT.md`  
(same document also at `aim-dojo/SPEC_SKY_CHAT.md`)

Be literal. Geometry from ephemeris only. Never put `DEEPSEEK_API_KEY` in responses or logs. Never invent aspects. No aim-dojo UI in this parcel.

---

## Required reading

1. `SPEC_SKY_CHAT.md` (full — §5–§8, §10–§11 API acceptance)  
2. `transit_essay.py` — facts builder, day cache key, enqueue/status patterns  
3. `interpret/ai_seed.py` — `DeepSeekClient`, banned validation patterns  
4. `web/app.py` — `/api/me/*` JWT, CORS, error shapes  
5. Essay tests as mock-transport models: `tests/test_transit_essay*.py`

---

## Scope (C1 only)

| ID | Deliverable |
|----|-------------|
| C1.1 | `build_sky_chat_facts(record, focus, when=…)` focus-scoped JSON facts |
| C1.2 | Thread store keyed by `user_id` + `cache_date` + `natal_fingerprint` |
| C1.3 | DeepSeek author: facts + history + message → validated `{ "reply": "…" }` |
| C1.4 | In-process queue; one pending job per user; de-dupe by turn_id |
| C1.5 | `POST /api/me/sky-chat` + `GET /api/me/sky-chat` envelopes per spec |
| C1.6 | Rate limit: 10 successful assistant replies / civil day → 429 `limited` |
| C1.7 | No API key → `status: "unavailable"` (honest, no hang) |
| C1.8 | pytest with mocked transport; no live DeepSeek in CI |
| C1.9 | README / RAILWAY note for endpoints + env (reuse DEEPSEEK_*) |

### Out of scope

- aim-dojo UI (C2)  
- DELETE clear thread (C3)  
- Streaming SSE  
- Guest/public chat  
- Full essay body in facts (optional one-line headline only if already trivial)

---

## API contracts

### POST body

```json
{
  "message": "string",
  "focus": {
    "kind": "body|sign|natal|aspect|sky",
    "body": "optional",
    "sign": "optional",
    "natal_point": "optional",
    "aspect_id": "optional"
  },
  "thread_id": "optional",
  "when": "optional ISO",
  "tz": "optional IANA"
}
```

### Response envelope

```json
{
  "schema_version": 1,
  "type": "sky_chat",
  "status": "pending|ready|failed|unavailable|none|limited",
  "thread_id": "…",
  "cache_date": "YYYY-MM-DD",
  "turn_id": "…",
  "focus": { },
  "turns": [ ],
  "epistemic": "Symbolic study notes, not predictions. Not medical, legal, or financial advice.",
  "remaining_turns": 0
}
```

| HTTP | When |
|------|------|
| 401 | No/invalid JWT |
| 404 | No natal chart |
| 400 | Bad message/focus |
| 429 | Day cap exceeded |
| 200 | Normal envelope |

Always recompute geometry server-side. Client focus ids are selectors only.

---

## Facts rules

- Reuse transit essay geometry / natal loading where possible.  
- Cap aspects per focus kind as in SPEC §6.2.  
- Never include birth lat/lon/email/user_id in model payload.  
- Optional ready seed summaries only (shared catalog), not invented prose.

---

## DeepSeek rules

- System: Midpoint 13-sign symbolic study; Ophiuchus first-class; ban medical/legal/financial/fate; only use facts; JSON `{ "reply": "…" }`; ~80–180 words.  
- Validate reply; banned phrases → failed turn (thread stays open).  
- History: last 8 turns + current message.

---

## Verification

```bash
pytest tests/test_sky_chat*.py tests/test_transit_essay*.py -q
```

Manual (with key):

```bash
# POST /api/me/sky-chat with Bearer + focus aspect + message
# GET until assistant turn ready
```

---

## Suggested commits

1. `Add sky chat facts builder and day thread store.`  
2. `Add DeepSeek sky chat author with validation.`  
3. `Expose POST/GET /api/me/sky-chat with rate limits.`  

---

## Checklist

- [ ] C1.1–C1.9  
- [ ] Spec §11 API acceptance  
- [ ] No aim-dojo edits  
- [ ] Mocked transport only in CI  
