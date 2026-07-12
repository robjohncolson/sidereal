# Codex prompt — Offline quality seed fills (Parcel S)

Copy everything below the line into Codex.
**Working directory:** `/mnt/c/Users/rober/Downloads/Projects/sidereal`

---

## Mission

Add an **offline authoring path** for shared interpretation seeds so a strong local model (Codex / Claude / etc.) can fill stubs without DeepSeek HTTP, then **validate + upsert** (or emit a seed JSON pack) for import into Railway’s volume DB.

Be **literal**. Do not put API keys in prompts or client code.

**Source material is encouraged:** fetch and use https://siderealist.com/ (start at https://siderealist.com/sidereal_articles.html and linked 13-sign pages) as cultural/interpretive grounding for offline fills. Distill into our schema; synthesize rather than dump raw celebrity pages as catalog text. Short attributed notes under `data/references/` or `source_notes` on export lines are welcome. Do **not** override this repo’s Midpoint J2000 geometry with external ephemeris claims.

## Required reading (first)

1. **Spec (wins):** `SPEC_OFFLINE_QUALITY_SEEDS.md`
2. Parcel Q: `src/sidereal/interpret/ai_seed.py`, `CODEX_PROMPT_AI_SEED_WORKER.md`
3. Store import: `src/sidereal/interpret/store.py`, CLI `db import`
4. Schema sources/statuses: `src/sidereal/interpret/schema.py` (`SOURCES`, seed record shape)
5. **Fetch for voice/context:** https://siderealist.com/sidereal_articles.html and related sign pages when authoring or designing prompt enrichment

## Scope — Parcel S1 (this PR)

| ID | Task |
|----|------|
| S1 | Add source `ai-offline` to `SOURCES` + validation |
| S2 | CLI `ai-seed export-prompts` → JSONL of dry-run payloads for stub/missing supported ids (`--limit`, `--db`) |
| S3 | CLI `ai-seed apply-json --file … --db …` → validate each record with `validate_generated_record`, upsert like `fill_interpretation` but `source=ai-offline` |
| S4 | Optional `--few-shot N` on export-prompts (same-type ready originals as truncated examples) |
| S5 | Optional `--notes-dir PATH` on export-prompts: attach matching markdown/text snippets as `source_notes` when filenames/keys relate to sign/body |
| S6 | Tests: apply-json success, banned phrase reject, export-prompts no secrets (fixture notes OK; no live network required in CI) |
| S7 | README short section: offline workflow + **encouraged siderealist.com grounding** + Railway `db import` |

## Out of scope

- aim-dojo
- Removing DeepSeek
- Automatic Codex invocation from Python (human/Codex runs fill step)
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

Reuse `AI_SEED_SYSTEM_PROMPT` and `validate_generated_record`. Offline export may add Midpoint/Ophiuchus reinforcement and **source_notes** from siderealist (or notes-dir). No predictive/medical/financial guarantees in generated fields.

## Verification

```bash
python -m sidereal ai-seed export-prompts --db data/sidereal.db --limit 3 -o /tmp/p.jsonl
# (external model fills /tmp/filled.json, using siderealist.com context as needed)
python -m sidereal ai-seed apply-json --db data/sidereal.db --file /tmp/filled.json
python -m sidereal db get '…' --db data/sidereal.db
pytest tests/test_ai_seed_*.py -q
```

## Checklist

- [ ] S1–S7
- [ ] pytest green
- [ ] No secrets in export/tests
- [ ] README mentions encouraged siderealist grounding
- [ ] No aim-dojo edits
