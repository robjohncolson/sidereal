# Offline quality seed fills (Parcel S)

**Status:** planned
**Depends on:** Parcel Q (`interpret/ai_seed.py`, store upsert, CLI)
**Related style reference (human reading only, do not scrape wholesale):**
https://siderealist.com/sidereal_articles.html — 13-sign sidereal culture, Ophiuchus-as-citizen, irreverent but symbol-literate voice. Prefer *attitude* (constellation-first, anti-tropical default, Ophiuchus normal) over copying celebrity bios or paywalled essays.

## Problem

Railway DeepSeek (`deepseek-v4-flash`) works for async stub fills, but:

1. Context is thin (system blurb + id + keywords only).
2. Batch quality is better done **offline** with a stronger author (Codex / Claude / local).
3. Production volume writes are easiest via `db import` or dashboard shell, not SSH from every agent environment.

## Goals

1. **Pluggable author** — DeepSeek remains the online default; offline tools can inject JSON without HTTP.
2. **Richer offline prompts** — optional few-shot from existing `source=original` / `ready` seeds; optional voice notes pointing at Midpoint 13-sign practice (not tropical).
3. **Export pack** — write a seed JSON file ready for `python -m sidereal db import …`.
4. **Import path documented** for Railway `/data/sidereal.db`.
5. **Epistemic safety unchanged** — same `validate_generated_record` + banned fragments; symbolic study only.

## Non-goals

- Per-user natal novels
- Scraping siderealist.com into the repo or prompts as full article text
- Replacing geometry / Midpoint boundaries
- aim-dojo UI changes (optional later: “source: ai” badge)

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

`export-prompts`: one JSONL line per stub/missing supported id = dry-run request + entry_id (no API keys).

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

or a single object with `id` + generated fields. Validated, then `upsert` with `source: "ai-offline"` (add to `SOURCES` if missing) or reuse `ai-deepseek` with a note in growth — prefer new source `ai-offline` for provenance.

`pack-stubs`: optional helper that emits inventory-shaped seed file after apply for git tracking.

### Prompt enrichment (offline only by default)

Optional flag `--few-shot N` on export-prompts:

- Pull up to N **ready** entries of the **same type** from the store (prefer `source=original`).
- Attach as abbreviated examples in the user message (title + summary only, truncated).
- System prompt may add one short bullet: *“Midpoint 13-sign true-sidereal; Ophiuchus is a full sign; constellation-aligned culture, not tropical personality columns.”*

Do **not** paste third-party article text into the repo.

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
- [ ] pytest covers apply-json happy path + validation failure
- [ ] README documents offline Codex workflow + Railway import
- [ ] No aim-dojo edits required

## Parcel order

| Parcel | Repo | Deliverable |
|--------|------|-------------|
| **S1** | sidereal | export-prompts + apply-json + source `ai-offline` + tests |
| **S2** | sidereal | optional few-shot on export; pack-stubs helper |
| **S3** | ops | fill remaining stubs offline; import to Railway |

DeepSeek online path remains Parcel Q; S does not remove it.
