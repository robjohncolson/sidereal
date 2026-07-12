# Codex prompt — Sky Listen API (Parcel J)

Copy everything below the line into Codex. Working directory: **sidereal**.

---

## Mission

Implement **`GET /api/sky-listen`**: short JSON for Moon Chorus when the player “listens” to a sky planet or sign — **(A) placement meaning** + **(B) personal transit meaning** when `natal_id` is provided. Reuse existing interpretation/transit compose. Local-only. No aim-dojo edits.

## Required reading

1. **Plan:** `/mnt/c/Users/rober/Downloads/Projects/aim-dojo/SPEC_SKY_LISTEN.md` §4, §6, §8 Parcel J, §9. **Plan wins.**
2. Code: `web/app.py`, `interpret/store.py`, `interpret/compose.py`, `interpret/transit.py`, `skypack.py`, chart library loaders.

## Scope

| ID | Deliverable |
|----|-------------|
| J1 | Route `GET /api/sky-listen` with query params |
| J2 | `placement` object from DB seeds (planet-in-sign and/or sign character) |
| J3 | `personal` object when natal loads; transit highlights + short text |
| J4 | pytest + README curl |
| J5 | No aim-dojo; no schema break of skypack |

## API contract

```text
GET /api/sky-listen
  natal_id optional string
  body optional string   # sun, moon, mercury, … pluto, north_node, …
  sign optional string   # midpoint sign id
  kind optional body|sign  # default: body if body set else sign
  when optional ISO local
  tz optional IANA
```

**400** if neither body nor sign usable.  
**404** if natal_id provided but missing.  
**200** always includes `schema_version`, `type: "sky_listen"`, `system: "midpoint_v1"`, `epistemic` string, `target`, `placement` (may be stub text if seed gap — say so honestly).

### placement (block A)

- Title like `Pluto in Libra` or `Libra`.  
- `text`: short symbolic paragraph from store (prefer real seed; if missing, explicit stub language, not invented long essay).  
- Optional `development` line if store has it.

### personal (block B)

If no `natal_id`: `{ "available": false }`.  
If natal present:

- `available: true`, `natal_id`, optional `delta_deg` for same-body sky vs natal if body set  
- `title` / `text`: transit-flavored study note (reuse transit compose snippets / relationship seeds where possible)  
- `highlights`: up to 5 tight transit→natal aspects involving this body (glyph, natal_point, orb)

Compute sky position at `when`/`tz` (default now) with same ephemeris path as skypack/transit.

## Guidelines

1. Pure functions where possible; thin route wrapper.  
2. Epistemic: never predictive/medical/financial claims in new copy.  
3. Match existing error/HTTP patterns in `app.py`.  
4. CORS: if game on `127.0.0.1:8931` cannot fetch, add minimal localhost dev allowance consistent with security middleware (document).  
5. Tests: placement present; personal available true/false; 404 natal; invalid params.

## Definition of done

- [ ] J1–J5  
- [ ] curl example in README  
- [ ] tests green  
- [ ] sample JSON printed in completion summary  

**Begin:** read SPEC_SKY_LISTEN.md §6, then implement the builder + route.
