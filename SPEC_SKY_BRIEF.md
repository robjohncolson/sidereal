# Daily Sky Brief — copy-paste export (Parcel B)

**Status:** planned  
**Version:** 1.0 · 2026-07-13  
**Depends on:** Parcel P (auth + natal), transit geometry / `build_transit_essay_facts`, aim-dojo Save my sky + pause UI  
**Repos:** sidereal (Railway) · aim-dojo (Vercel client)

---

## 1. Product intent

A signed-in player with a saved chart can open **pause** and copy a **daily plain-text sky brief**: natal placements + today’s transit movers + ranked transit→natal contacts (optional essay appendix if ready). They paste that block into **another LLM** for personal study.

- Generated / cached **once per civil day** (natal timezone), same day key as the personal transit essay.
- **Facts-first** (ephemeris geometry) — **no DeepSeek required** for the brief itself.
- Essay prose is **optional** appendix when TODAY’S SKY NOTE is already ready.
- Play is never blocked; export is **pause-only**, user-initiated.

---

## 2. Goals / Non-goals

### Goals

1. One pause control: **TODAY’S SKY BRIEF** (or nested under SAVE MY SKY) with scrollable text + **COPY BRIEF**.
2. Server builds a stable **LLM-ready plain-text** document from `build_transit_essay_facts` (and optional ready essay).
3. Daily cache: `user_id` + `cache_date` + `natal_fingerprint` (same invalidation as transit essay).
4. Epistemic footer in every paste block; symbolic study only.
5. Privacy: never leaderboard, share URL, multiplayer, or public sky-day.

### Non-goals (v1)

- Multi-day history browser  
- Auto-email of the brief  
- Client-side Swiss ephemeris  
- Replacing TODAY’S SKY NOTE reader  
- Including raw birth lat/lon in the paste by default (placements + `time_unknown` + tz are enough)  
- Re-enabling groove pocket language  

---

## 3. Privacy rails (hard)

| Rule | Detail |
|------|--------|
| Auth | Bearer JWT only; 401 without session |
| Chart | 403/404 pattern consistent with natal/essay if no chart |
| Paste | User clicks COPY; no auto clipboard |
| Omit from export | Raw `lat` / `lon` / email / user_id / access tokens |
| Include | Natal **placements**, `time_unknown`, `tz`, transit movers, aspects, `cache_date`, `epoch_utc` |
| Surfaces | Never attach brief to share link, dojo POST, presence, or guest UI |
| Epistemic | Fixed footer string in text (same spirit as essay) |

---

## 4. Text document format (canonical paste)

Server-rendered **UTF-8 plain text**, LF newlines, no HTML. Sections in order:

```text
# Moon Chorus sky brief
date: {cache_date} ({timezone})
epoch_utc: {epoch_utc}
frame: sidereal / 13-sign midpoints (as product already uses)
epistemic: Symbolic study notes, not predictions. Not medical, legal, or financial advice.

## Natal placements
{one line per body/angle, e.g. Sun · Scorpio · 12.3° · house 5}
{if time_unknown: note that houses/angles may be omitted or marked uncertain}

## Today’s movers (transit)
{one line per mover: Mars · Leo · 4.1° · Rx · natal house 7}

## Transit → natal contacts
{ranked; e.g. Transit Mars square natal Moon · orb 1.2° · applying}
{up to same max_aspects as essay facts}

## Same-body deltas (optional short list)
{e.g. Sun · transit vs natal separation 47.2°}

## Today’s sky note (only if essay ready)
headline: …
body:
…
watchpoints:
- …
```

**Display names:** human-readable body/sign/aspect labels (Title Case), consistent with existing Listen/essay display helpers where possible.

**Language:** English v1 for the export document (i18n of pause chrome only; paste is for external LLMs — EN is fine).

---

## 5. API (sidereal)

### `GET /api/me/sky-brief`

**Auth:** required  
**Query:** none required; server uses “now” + stored natal.

**Behavior:**

1. Load natal record for user; if missing → error consistent with other `/api/me/*` chart gates.  
2. Resolve `cache_date` via `transit_essay_cache_date(record, now)`.  
3. Load or build facts (`build_transit_essay_facts`); may reuse essay-pipeline facts cache if present for same fingerprint/day.  
4. Format plain text via `format_sky_brief_text(facts, essay=optional)`.  
5. If transit essay for that day is `ready`, append **Today’s sky note** section (headline/body/watchpoints + epistemic). If pending/failed/absent, omit that section (brief still ready).  
6. Return JSON:

```json
{
  "status": "ready",
  "cache_date": "2026-07-13",
  "timezone": "America/New_York",
  "text": "# Moon Chorus sky brief\n…",
  "has_essay": false,
  "epistemic": "Symbolic study notes, not predictions. …"
}
```

**Status values (v1):**

| status | Meaning |
|--------|---------|
| `ready` | `text` present (facts always computable if natal + ephemeris OK) |
| `failed` | Soft fail: geometry/ephemeris/store error; client shows quiet message |

No `pending` for facts-only brief (sync build is OK if &lt; ~1–2s; if too slow, optional short-term cache warm on natal save / essay enqueue — not required if current essay facts build is already acceptable).

**Errors:**

- 401 unauthenticated  
- 404 / structured error if no natal (match existing style)  
- 503 if service unavailable  

### Optional `GET /api/me/sky-brief.json`

Same payload plus `"facts": { … }` (raw `transit_essay_facts` object, still **without** lat/lon). Power-user; v1 may skip if time-boxed.

### Caching

- Prefer reuse of facts already stored for transit essay for `(user, cache_date, natal_fingerprint)`.  
- If no cache: compute, optionally store as facts row for essay pipeline reuse.  
- On natal update / delete: invalidate like transit essay.

---

## 6. Client UX (aim-dojo)

### Placement

Pause **settings** area, near SAVE MY SKY / TODAY’S SKY NOTE:

- Block **hidden** for guests / no chart.  
- Visible when authenticated + `hasChart` (same gate as essay button).

### Controls

| Element | Behavior |
|---------|----------|
| Label | `TODAY’S SKY BRIEF` |
| Status | `READY · {cache_date}` / `UNAVAILABLE` / `SIGN IN · SAVE YOUR SKY` |
| Textarea or pre | Read-only scrollable monospace preview (max-height ~12rem) |
| **COPY BRIEF** | `navigator.clipboard.writeText(text)`; toast `BRIEF COPIED`; fallback select+copy if clipboard denied |
| Refresh | Optional small control; or re-fetch each time pause opens (simple) |

### Lifecycle

1. On pause open (or when chart becomes available): if gate OK, `GET /api/me/sky-brief`.  
2. Show preview from `text`.  
3. COPY uses last successful `text`.  
4. Day rollover: next fetch returns new `cache_date`.  
5. Do **not** enqueue DeepSeek solely for the brief.  
6. Essay toast flow unchanged; if essay becomes ready mid-session, next brief fetch may include note section.

### Privacy copy

Help line: `Private · for pasting into another study tool · not shared with the board`

### i18n

Pause chrome via `T()` + `window.JA`. Paste body stays EN (spec §4).

---

## 7. `save-my-sky.js`

Extend controller:

```js
getSkyBrief() → GET /api/me/sky-brief
// normalize { status, cache_date, text, has_essay, epistemic }
```

Same Bearer / base URL as natal and transit essay. Fail soft.

---

## 8. Implementation map

### Server (sidereal)

| Piece | Notes |
|-------|--------|
| `format_sky_brief_text(facts, essay=None) -> str` | Pure; unit-testable |
| `GET /api/me/sky-brief` | In `web/app.py` next to transit-essay routes |
| Reuse | `build_transit_essay_facts`, natal load, essay get-if-ready |
| Tests | format fixtures; route auth; no lat/lon in text; cache_date |

### Client (aim-dojo)

| Piece | Notes |
|-------|--------|
| Pause markup + CSS | Nested under settings / sky section |
| Fetch on pause / chart ready | No combat path |
| COPY + toast | Clipboard API |
| Tests | Contract: button gated; no birth coords in share; brief not in dojo body |

---

## 9. Acceptance

1. Guest: no brief fetch; block hidden.  
2. Signed-in + chart: GET returns `ready` + non-empty `text` with natal + movers + aspects sections.  
3. `text` contains epistemic line; does **not** contain lat/lon/email patterns.  
4. COPY places full text on clipboard (or documented fallback).  
5. Essay pending: brief still ready without note section; essay ready: note section present.  
6. Natal change: brief rebuilds (new fingerprint / invalidation).  
7. Share / dojo payloads unchanged (no brief fields).  
8. Play path never waits on brief.

---

## 10. Out of scope follow-ups

- JA paste localization  
- Multi-day archive  
- PDF download  
- Including raw birth coordinates behind an explicit toggle  

---

## 11. Summary

**Pause-only daily text export of natal + today’s transits for pasting into another LLM, built from existing transit-essay facts, cached per civil day, no DeepSeek dependency, strict privacy.**
