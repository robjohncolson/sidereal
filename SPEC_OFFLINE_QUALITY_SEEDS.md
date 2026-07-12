# Offline quality seed fills (Parcel S)

**Status:** planned
**Depends on:** Parcel Q (`interpret/ai_seed.py`, store upsert, CLI)

**Primary external material (encouraged):**
https://siderealist.com/ — especially https://siderealist.com/sidereal_articles.html and linked 13-sign pages.

Agents **should** fetch and use this site as grounding for offline fills: constellation-first / Midpoint-adjacent 13-sign culture, Ophiuchus as a full citizen, irreverent symbol-literate voice. Distill into our catalog schema (title / summary / growth / keywords). Prefer transforming and synthesizing over dump-paste of whole celebrity bios; short attributed excerpts in prompt context or `data/references/` notes are fine when they improve fidelity.

## Problem

Railway DeepSeek (`deepseek-v4-flash`) works for async stub fills, but:

1. Context is thin (system blurb + id + keywords only).
2. Batch quality is better done **offline** with a stronger author (Codex / Claude / local) **plus** real sidereal-culture source material.
3. Production volume writes are easiest via `db import` or dashboard shell, not SSH from every agent environment.

## Goals

1. **Pluggable author** — DeepSeek remains the online default; offline tools can inject JSON without HTTP.
2. **Richer offline prompts** — few-shot from existing `source=original` / `ready` seeds **and** optional scraped/distilled notes from siderealist.com (and similar 13-sign sources the operator approves).
3. **Export pack** — write a seed JSON file ready for `python -m sidereal db import …`.
4. **Import path documented** for Railway `/data/sidereal.db`.
5. **Epistemic safety unchanged** — same `validate_generated_record` + banned fragments; symbolic study only (no medical/financial/fate guarantees).

## Non-goals

- Per-user natal novels
- Replacing geometry / Midpoint boundaries
- aim-dojo UI changes (optional later: “source: ai” badge)
- Requiring network access inside CI tests (scrape/export can be offline-prepared fixtures)

## Design

### Author protocol

```text
SeedAuthor.generate(prompt: SeedPrompt) -> GeneratedSeedContent
```

Implementations:

| Author | Use |
|--------|-----|
| `DeepSeekClient` | Online queue + CLI `ai-seed fill` (existing) |
| `JsonFileAuthor` / stdin | Offline Codex output validated then upserted |
| `RecordingAuthor` | Tests |

### Source material workflow (encouraged)

1. Fetch relevant pages from siderealist.com (articles index, sign pages, Ophiuchus, etc.).
2. Distill into short **context blocks** per topic (sign / body / aspect class) — either:
   - injected into exported prompt JSONL as `source_notes`, or
   - saved under `data/references/siderealist/` as markdown notes for human/Codex reuse.
3. Author fills **our** JSON fields from inventory id + keywords + source notes + few-shot ready seeds.
4. Apply via `apply-json` so validation still gates banned predictive/medical language.

Do **not** treat siderealist.com as geometric authority over this repo’s Midpoint J2000 boundaries; it is **cultural / interpretive** context.

### CLI additions (Parcel S)

```bash
# Existing
python -m sidereal ai-seed dry-run --id '…'
python -m sidereal ai-seed fill --id '…' --db data/sidereal.db
python -m sidereal ai-seed fill-gaps --db data/sidereal.db --limit 10

# New
python -m sidereal ai-seed export-prompts --db data/sidereal.db --limit 20 -o /tmp/prompts.jsonl
python -m sidereal ai-seed apply-json --db data/sidereal.db --file /tmp/filled.json
python -m sidereal ai-seed pack-stubs --db data/sidereal.db --limit 20 -o data/seeds/seed_13_offline_ai_v1.json
```

`export-prompts`: one JSONL line per stub/missing supported id = dry-run request + entry_id (no API keys). May include optional `source_notes` when provided via `--notes-dir` or embedded few-shot.

`apply-json`: file shape either:

```json
{
  "schema_version": 1,
  "records": [
    {
      "id": "aspect:asc:conjunction:mc",
      "title": "…",
      "summary": "…",
      "growth": "…",
      "keywords": ["…"]
    }
  ]
}
```

or a single object with `id` + generated fields. Validated, then `upsert` with `source: "ai-offline"` (add to `SOURCES`).

`pack-stubs`: optional helper that emits inventory-shaped seed file after apply for git tracking.

### Prompt enrichment (offline)

Optional flag `--few-shot N` on export-prompts:

- Pull up to N **ready** entries of the **same type** from the store (prefer `source=original`).
- Attach as abbreviated examples in the user message (title + summary only, truncated).
- System / user context should reinforce Midpoint 13-sign true-sidereal and Ophiuchus-as-citizen.
- **Encouraged:** attach distilled siderealist (or notes-dir) excerpts relevant to that id’s sign/body.

### Production upload

```bash
# After local apply-json or pack
python -m sidereal db import data/seeds/seed_13_offline_ai_v1.json --db data/sidereal.db

# On Railway volume (dashboard shell)
python -m sidereal db import /tmp/seed_13_offline_ai_v1.json --db /data/sidereal.db
```

Or `fill-gaps` still runs online for residual stubs.

## Acceptance

- [ ] `export-prompts` produces key-free JSONL
- [ ] `apply-json` validates and upserts; rejects banned fragments
- [ ] New source value accepted by schema
- [ ] pytest covers apply-json happy path + validation failure (no live scrape required in CI)
- [ ] README documents offline Codex workflow, **source material fetch encouraged**, Railway import
- [ ] No aim-dojo edits required

## Parcel order

| Parcel | Repo | Deliverable |
|--------|------|-------------|
| **S1** | sidereal | export-prompts + apply-json + source `ai-offline` + tests |
| **S2** | sidereal | few-shot + optional notes-dir / source_notes; pack-stubs |
| **S3** | ops + author | scrape/distill siderealist → fill remaining stubs offline → import Railway |

DeepSeek online path remains Parcel Q; S does not remove it.
