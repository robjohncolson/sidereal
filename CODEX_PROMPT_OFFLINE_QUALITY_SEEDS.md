# Codex prompt — Offline quality seed fills (Parcel S)

Copy everything below the line into Codex.
**Working directory:** `/mnt/c/Users/rober/Downloads/Projects/sidereal`

---

## Mission

Add an **offline authoring path** for shared interpretation seeds so a strong local model (Codex / Claude / etc.) can fill stubs without DeepSeek HTTP, then **validate + upsert** (or emit a seed JSON pack) for import into Railway’s volume DB.

Be **literal**. Do not scrape third-party sites into the repo. Do not put API keys in prompts or client code.

## Required reading (first)

1. **Spec (wins):** `SPEC_OFFLINE_QUALITY_SEEDS.md`
2. Parcel Q: `src/sidereal/interpret/ai_seed.py`, `CODEX_PROMPT_AI_SEED_WORKER.md`
3. Store import: `src/sidereal/interpret/store.py`, CLI `db import`
4. Schema sources/statuses: `src/sidereal/interpret/schema.py` (`SOURCES`, seed record shape)
5. Style *reference only* (human): https://siderealist.com/sidereal_articles.html — 13-sign sidereal culture, Ophiuchus as a full citizen. **Do not download or paste article bodies** into seeds or code.

## Scope — Parcel S1 (this PR)

| ID | Task |
|----|------|
| S1 | Add source `ai-offline` to `SOURCES` + validation |
| S2 | CLI `ai-seed export-prompts` → JSONL of dry-run payloads for stub/missing supported ids (`--limit`, `--db`) |
| S3 | CLI `ai-seed apply-json --file … --db …` → validate each record with `validate_generated_record`, upsert like `fill_interpretation` but `source=ai-offline` |
| S4 | Optional `--few-shot N` on export-prompts (same-type ready originals as truncated examples) |
| S5 | Tests: apply-json success, banned phrase reject, export-prompts no secrets |
| S6 | README short section: offline workflow + Railway `db import` |

## Out of scope

- aim-dojo
- Removing DeepSeek
- Automatic Codex invocation from Python
- Full catalog fill in one PR

## Apply-json file shapes

Accept either:

```json
{ "schema_version": 1, "records": [ { "id": "…", "title": "…", "summary": "…", "growth": "…", "keywords": [] } ] }
```

or a single record object with `id` + generated fields.

On success print a batch summary (`filled` / `skipped` / `invalid`) as JSON.

## Upsert rules

Mirror `fill_interpretation`:

- Only supported inventory ids (`sign` / `planet_in_sign` / `aspect`)
- Bump version from current stub/ready when replacing stub
- `status=ready`, `license=personal-use`, `source=ai-offline`
- Race/conflict handling consistent with store

## Epistemic

Reuse `AI_SEED_SYSTEM_PROMPT` and `validate_generated_record` unchanged except optional one-line Midpoint/Ophiuchus reinforcement in **export** user messages when `--few-shot` is set. No predictive/medical/financial claims.

## Verification

```bash
python -m sidereal ai-seed export-prompts --db data/sidereal.db --limit 3 -o /tmp/p.jsonl
# (external model fills /tmp/filled.json)
python -m sidereal ai-seed apply-json --db data/sidereal.db --file /tmp/filled.json
python -m sidereal db get '…' --db data/sidereal.db
pytest tests/test_ai_seed_*.py -q
```

## Checklist

- [ ] S1–S6
- [ ] pytest green
- [ ] No network in tests
- [ ] No third-party article text committed
- [ ] No aim-dojo edits
