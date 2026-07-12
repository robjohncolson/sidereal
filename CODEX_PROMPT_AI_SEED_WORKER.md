# Codex prompt — AI seed worker / DeepSeek (Parcel Q)

Copy everything below the line into Codex.
**Working directory:** `/mnt/c/Users/rober/Downloads/Projects/sidereal`

---

## Mission

Implement an **async interpretation seed filler** that uses the **DeepSeek API** to author missing/stub catalog entries (shared keys, not per-user essays). Validated output is written into the existing interpretation SQLite store so compose / sky-listen improve for everyone.

Be **literal**. Never put the API key in client code. Never block HTTP handlers on long model calls by default.

## Required reading (first)

1. **Program plan:**
   `/mnt/c/Users/rober/Downloads/Projects/aim-dojo/SPEC_PUBLIC_TRANSITS_AND_AI_SEEDS.md`
   §6 (AI seed catalog), §8 env, §10–11. **Plan wins.**

2. Existing: `interpret/schema.py`, `interpret/store.py`, seed JSON shape in `data/seeds/`, `sky_listen.py` gap/stub behavior.

## Scope — Parcel Q

| ID | Task |
|----|------|
| Q1 | Banned-phrase + schema **validator** for generated records |
| Q2 | DeepSeek HTTP client (env-configured); dry-run mode without key |
| Q3 | Prompt templates per type: `planet_in_sign`, `aspect`, `sign` |
| Q4 | `fill_interpretation(id)` → validate → store upsert with version rules |
| Q5 | CLI: `ai-seed fill`, `ai-seed fill-gaps`, `ai-seed dry-run` |
| Q6 | In-process queue with de-dupe; optional `enqueue_ai_seed` from sky-listen miss |
| Q7 | Tests with mocked HTTP; no network in CI |

## Out of scope

- aim-dojo UI
- Supabase
- Guaranteeing full catalog fill in one PR (mechanism > completeness)
- Changing geometry/ephemeris

## Key design rules

1. **IDs only** — e.g. `planet_in_sign:saturn:pisces`, `aspect:moon:trine:saturn` (use store’s canonical body order).
2. **One fill per id** shared by all users.
3. **Epistemic:** symbolic Midpoint language; ban predictive/medical/financial/crisis phrasing.
4. Default HTTP path: **enqueue + return**; worker processes queue in background thread or CLI.
5. If `DEEPSEEK_API_KEY` missing: CLI errors clearly; enqueue no-ops or logs.

## Env

```text
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

(Use current DeepSeek chat completions URL/docs; keep base URL configurable.)

## Output schema (model must return JSON)

```json
{
  "title": "string",
  "summary": "string",
  "growth": "string",
  "keywords": ["string"]
}
```

Map into existing `InterpretationEntry` / seed import fields (`status: ready`, source `original` or `ai-deepseek`, license `personal-use` or project standard).

## Validator (must reject)

- Empty title/summary
- Summary too short (< 40 chars) or absurdly long (> 4000)
- Case-insensitive banned fragments: `you will`, `you are going to`, `diagnos`, `prescrib`, `cure your`, `lottery`, `guaranteed`, `destined to die`, etc. (maintain a frozenset)
- Invalid id type / unknown planet/sign tokens

## CLI

```bash
python -m sidereal ai-seed dry-run --id 'planet_in_sign:mars:aries'
python -m sidereal ai-seed fill --id 'planet_in_sign:mars:aries' --db data/sidereal.db
python -m sidereal ai-seed fill-gaps --db data/sidereal.db --limit 10
```

`fill-gaps` should list stub/missing from store audit or seed inventory and fill up to `--limit`.

## sky-listen hook (optional but preferred)

When personal/placement compose finds stub/missing:

```python
enqueue_ai_seed(entry_id)  # non-blocking
```

Do not await the model inside the request.

## Tests

- Validator unit tests (pass/fail samples)
- Mock DeepSeek response → store contains ready entry
- De-dupe: two enqueues → one worker job
- dry-run does not write

## Definition of done

- [ ] Q1–Q7
- [ ] pytest green without real API key
- [ ] README: env + CLI examples + “shared catalog” explanation
- [ ] No aim-dojo edits

**Begin:** read program SPEC §6, implement validator + dry-run CLI, then mocked fill.
