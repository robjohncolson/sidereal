# Sidereal

Sidereal is a local, offline-first Python tool for calculating a 13-sign,
unequal-boundary Midpoint chart and joining it to a personal SQLite library of
symbolic interpretations. Ophiuchus is a first-class sign.

> **Epistemic contract:** planetary positions, angles, houses, and aspects are
> reproducible astronomy/geometry. Interpretations are cultural and symbolic
> study notes, not empirical science, diagnosis, financial advice, or fate.

`SPEC.md` is the authoritative calculation and product contract.

## Requirements and installation

- Python 3.11 or newer
- `pyswisseph` (installed by the project; imported in Python as `swisseph`)
- `pytest` for development/testing
- FastAPI and Uvicorn only when using the optional local web desk

Create an isolated environment and install the package:

```bash
python3 -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m sidereal --help
```

To develop or run the browser UI, install the optional web dependencies too:

```bash
python -m pip install -e ".[dev,web]"
```

On this repository's WSL environment the system command is `python3`; after
activation the virtual environment provides `python` as used below.

## Swiss Ephemeris data

The binding can calculate modern charts with its documented Moshier fallback.
The report records which backend actually answered. For strict Swiss Ephemeris
file-backed calculation, put legally obtained `.se1` files directly in
`data/ephe/` and add both flags:

```bash
python -m sidereal chart ... \
  --ephe-path data/ephe \
  --require-swiss-ephemeris
```

For common modern dates, the official Swiss Ephemeris repository provides the
planet and Moon files:

```bash
curl -fL -o data/ephe/sepl_18.se1 \
  https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/sepl_18.se1
curl -fL -o data/ephe/semo_18.se1 \
  https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/semo_18.se1
```

With those files present, charts use backend `swisseph` (no Moshier warning).
Force that path with `--ephe-path data/ephe --require-swiss-ephemeris`.

For other date ranges, use the
[official Astrodienst download guide](https://www.astro.com/swisseph/swedownload_e.htm).
Ephemeris binaries are intentionally gitignored (large, separate license). Once
the dependency and needed files are present, chart calculation makes no network
calls.

## Interpretation database

Create a local database and import the shipped inventory/seeds:

```bash
python -m sidereal db init --db data/sidereal.db
python -m sidereal db import --db data/sidereal.db
python -m sidereal db gaps --db data/sidereal.db
python -m sidereal db get planet_in_sign:sun:virgo --db data/sidereal.db
```

With no path, `db import` resolves the checked-in seeds in an editable install
or the packaged seeds in a wheel; `SIDEREAL_SEED_PATH` can override it. Passing
`data/seeds/` explicitly remains supported. The import is safe to repeat.

Shipped seeds:

| File | Role |
|------|------|
| `seed_0_inventory_v1.json` | Full 967-key inventory as stubs |
| `seed_1_core_v1.json` | 76 ready primers (signs, houses, planets, Sun/Moon×sign, Asc×sign) |
| `seed_2_personal_aspects_v1.json` | 105 ready major aspects among Sun–Saturn |
| `seed_3_placements_v1.json` | 256 ready personal-planet×house, sign×house, Midheaven×sign, and pattern readings |
| `seed_4_placements_v1.json` | 99 ready Mercury/Venus/Mars×sign and Uranus/Neptune/Pluto/lunar-node×house readings |
| `seed_5_relationships_v1.json` | 210 ready personal↔outer/North Node and personal↔Ascendant/Midheaven major-aspect readings |
| `seed_6_self_aspects_v1.json` | 35 ready same-body transit aspects for Sun–Saturn |
| `seed_7_sign_character_v1.json` | 91 ready Jupiter–Pluto + lunar nodes × all 13 Midpoint signs (zodiac character) |
| `seed_8_bobby_chart_deep_v1.json` | 43 deeper placement and natal-aspect readings |
| `seed_9_parents_deep_v1.json` | 86 deeper placement and natal-aspect readings shared across two charts |
| `seed_10_family_synastry_v1.json` | 66 sign-agnostic family synastry aspect readings |
| `seed_11_family_placements_v1.json` | 101 v7 placement readings active across the three family studies |
| `seed_12_family_tight_aspects_v1.json` | 57 v7 sign-agnostic aspect readings active at 2° exactness or tighter |
| `seed_13_offline_ai_v1.json` | 69 validated offline-authored outer/node and angle aspect readings |

After import: **966 ready**, **1 stub**, **0 missing**. Seed 6 expands the
inventory with all five major same-body aspect keys for the planets and North
Node that can occur on both sides of a transit. Its 35 Sun–Saturn readings are
ready; Seed 13 later upgrades the remaining supported outer/node/angle backlog
while leaving `aspect:asc:conjunction:mc` as the sole explicit stub. Seed 7
completes planet/node × Midpoint-sign character so aspect reports can attach
zodiac color (not only planet-to-planet lore). Seeds 3–4 cover every
sign—including Ophiuchus—on every house cusp, Mercury/Venus/Mars in every sign,
all twelve houses for Sun through Pluto, and both calculated lunar nodes in
every house. Seed 5 fills the highest-value remaining relationship language.
Seeds 8–10 establish deeper family-study text. Seeds 11–12 supersede every
placement active in the three selected natal reports and every inventory-backed
aspect at 2° exactness or tighter across those natal and synastry reports with
version 7 prose. Shared aspects remain sign-agnostic because the compose layer
adds each chart's Midpoint sign character. Ascendant↔Ascendant and
Midheaven↔Midheaven geometry stays explicitly `not_applicable`; no angle
self-keys are added to the inventory. The family seed files contain no birth
moments, coordinates, saved-chart identifiers, or report snapshots.
`gaps` audits the complete inventory. `SIDEREAL_DB` changes the default
`data/sidereal.db` path; legacy `SIDEREAL_DB_PATH` remains a fallback. A chart
still calculates if that database does not exist; its report lists the
interpretation keys as missing.

The interpretation database schema is version 2. Opening an existing version
1 database for `db import` performs a transactional, data-preserving migration
that permits the new same-body aspect rows. Seed JSON remains version 1.

Scope the gap audit to the interpretations actually used by a report or saved
chart when deciding what to author next:

```bash
python -m sidereal db gaps --db data/sidereal.db
python -m sidereal db gaps --db data/sidereal.db \
  --chart reports/me.json
python -m sidereal db gaps --db data/sidereal.db \
  --chart-id "Me" --charts-dir charts
```

`--chart` reads a full report JSON. `--chart-id` resolves a local saved-chart id
or unambiguous label and composes its current interpretation key set. The
result reports ready, stub, and missing ids only within that scope.

### AI-assisted shared seed fills

Parcel Q can fill a missing or stub catalog record through DeepSeek. A fill is
keyed only by the shared interpretation id—such as
`planet_in_sign:mars:aries` or `aspect:moon:trine:saturn`—so the resulting text
serves every user who encounters that geometry. Prompts contain the id and
inventory keywords only; they never contain a user id, birth data, chart
coordinates, or a personalized essay request.

```bash
# No API key, network call, or database write:
python -m sidereal ai-seed dry-run \
  --id 'planet_in_sign:mars:aries'

# Requires an initialized interpretation database and server-side key:
python -m sidereal ai-seed fill \
  --id 'aspect:moon:trine:saturn' --db data/sidereal.db
python -m sidereal ai-seed fill-gaps \
  --limit 10 --db data/sidereal.db
```

| Variable | Purpose |
|----------|---------|
| `DEEPSEEK_API_KEY` | Server-only credential; required by fill commands and never returned to clients |
| `DEEPSEEK_MODEL` | Optional model override; defaults to current `deepseek-v4-flash` |
| `DEEPSEEK_BASE_URL` | Optional API base; defaults to `https://api.deepseek.com` |
| `SIDEREAL_DB` | SQLite path, preferably on a persistent Railway volume |

The client uses DeepSeek's non-streaming
[`POST /chat/completions`](https://api-docs.deepseek.com/api/create-chat-completion)
JSON-output contract. Generated objects must contain exactly `title`,
`summary`, `growth`, and `keywords`; deterministic validation rejects malformed,
predictive, medical, financial, legal, crisis, and guaranteed-outcome language
before SQLite is touched. Ready/user-authored records are never overwritten;
stub fills increment the existing version and use source `ai-deepseek`.

When `DEEPSEEK_API_KEY` and the interpretation database are present, Sky
Listen queues missing/stub ids in a bounded background worker and returns its
current geometry/text immediately. Queued and in-flight ids are de-duplicated
within the process. A failed fill leaves the stub unchanged and can be retried
on a later request; the next request sees a successfully committed ready entry.
Without the key, the HTTP hook is inert.

### Offline shared seed authoring

The same shared catalog can be authored without DeepSeek HTTP. Export bounded,
key-free prompt payloads, have a strong local or hosted author return each id
plus the four generated fields, then validate and apply them locally:

```bash
python -m sidereal ai-seed export-prompts \
  --db data/sidereal.db --limit 20 --few-shot 2 \
  -o /tmp/sidereal-prompts.jsonl

# Optional when you have prepared local cultural notes:
#   --notes-dir data/references/siderealist

# Accepts one {id, title, summary, growth, keywords} object or this wrapper:
# {"schema_version": 1, "records": [...]}
python -m sidereal ai-seed apply-json \
  --db data/sidereal.db --file /tmp/sidereal-filled.json
```

`export-prompts` selects only missing/stub `sign`, `planet_in_sign`, and
`aspect` ids. `--few-shot` adds abbreviated ready records of the same type,
preferring `source=original`. `--notes-dir` attaches matching UTF-8 Markdown or
text snippets by sign/body filename or metadata key. Neither option includes an
API key, personal chart data, or an automatic model invocation.

Grounding from the [Siderealist articles index](https://siderealist.com/sidereal_articles.html),
its [13-sign overview](https://siderealist.com/13signs.html), and linked sign
pages is encouraged for constellation-first culture, vivid symbols, and
Ophiuchus as a full citizen. Distill and synthesize that material into
inclusive capacity/shadow/growth language; do not copy celebrity biographies,
deterministic stereotypes, medical claims, or sign-date tables. External source
material is interpretive context only and never overrides this repository's
Midpoint J2000 geometry.

`apply-json` runs the same exact-field and banned-phrase validator as the online
worker. Valid stub/missing records become `status=ready`,
`source=ai-offline`, `license=personal-use`, with the baseline version bumped;
ready and user-authored records are skipped. Its JSON summary reports `filled`,
`skipped`, and `invalid` counts.

The direct Railway-volume path is to upload the compact filled JSON and run the
same validator/upsert command from the dashboard shell:

```bash
python -m sidereal ai-seed apply-json --file /tmp/sidereal-filled.json \
  --db /data/sidereal.db
```

For a reviewable, repeatable promotion artifact, extract the locally accepted
rows in the full `InterpretationEntry` shape used under `data/seeds/`, preserve
their already-bumped versions, and import that versioned pack on Railway:

```bash
python -m sidereal db import /tmp/seed_13_offline_ai_v1.json \
  --db /data/sidereal.db
```

The compact `apply-json` author response is not itself a `db import` pack;
`db import` expects `schema_version: 1` plus complete inventory-shaped records.

## Calculate a chart

With known time and coordinates (longitude is east-positive):

```bash
python -m sidereal chart \
  --date 2000-01-01 \
  --time 12:00 \
  --tz UTC \
  --lat 0 --lon 0 \
  --label "Example" \
  --out /tmp/example.json \
  --md /tmp/example.md \
  --svg /tmp/example.svg
```

Without a known time:

```bash
python -m sidereal chart \
  --date 1990-06-15 \
  --tz UTC \
  --no-houses \
  --out /tmp/date-only.json \
  --md /tmp/date-only.md
```

Date-only charts use **12:00 local time as an explicit calculation
convention**, which minimizes the maximum time error within the civil date.
Metadata labels that assumption and `time_known=false`. Angles, house cusps,
house assignments, and aspects to angles remain absent; fast-moving bodies,
especially the Moon, remain time-uncertain. Sidereal never presents noon as a
user-supplied birth time.

If `--out`, `--md`, and `--svg` are all omitted, the full JSON report is
printed to stdout. Output parent directories are created when needed. Use
`--no-houses` to suppress houses even if time and coordinates are supplied.

`--svg` writes a deterministic, standalone 13-sign Midpoint wheel. If it is
omitted while `--out` or `--md` is present, Sidereal derives an `.svg` path
beside the JSON (preferred) or Markdown report and links it from Markdown.
The unequal canonical sign arcs include Ophiuchus; house cusps appear only for
known-time charts, with the Ascendant oriented at 9 o'clock. Rendering consumes
the chart's existing J2000 geometry and performs no second calculation.

### Compare Midpoint and tropical labels

Midpoint remains the primary system. Add `--compare tropical` (equivalently,
`--compare midpoint,tropical`) to place a geometry-only comparison in JSON and
Markdown:

```bash
python -m sidereal chart \
  --date 2000-01-01 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --compare tropical \
  --db data/sidereal.db \
  --out /tmp/comparison.json --md /tmp/comparison.md
```

The tropical side uses twelve equal 30° signs from 0° Aries on tropical
ecliptic longitude of date. Midpoint uses the unequal J2000 boundary table.
The report flags differing sign labels without treating either reference frame
as uniquely true. Houses, aspects, and the moment are not recomputed, and only
the primary Midpoint placements are joined to interpretation records.

## Save charts locally

The chart library stores one strict JSON file per chart under gitignored
`charts/`. These files contain birth date, time, timezone, coordinates, and
full geometry; treat them as sensitive personal data and back them up or share
them only deliberately.

```bash
python -m sidereal save \
  --label "Me" --date 2000-12-12 --time 12:00 --tz UTC \
  --lat 0 --lon 0 --compare tropical
python -m sidereal list
python -m sidereal show "Me"
python -m sidereal show "Me" --md /tmp/me-geometry.md --out /tmp/me-saved.json
python -m sidereal interpret "Me" --db data/sidereal.db \
  --md /tmp/me-current.md --out /tmp/me-current.json
```

`show` reads the saved geometry snapshot; `interpret` joins that snapshot to
the current SQLite content, so seed updates do not require saving the chart
again. `--charts-dir PATH` or `SIDEREAL_CHARTS_DIR` selects another local
library. Repeated labels are allowed; use the id printed by `list` when a label
is ambiguous.

IANA daylight-saving transitions can repeat a local wall time. Sidereal rejects
that ambiguity unless it is resolved explicitly: add `--fold 0` for the first
occurrence or `--fold 1` for the second. Nonexistent wall times during a spring
clock jump are rejected. Latitude must be strictly between -90° and 90°;
longitude must be between -180° and 180°.

Historical timezone rules, especially before 1970, vary in completeness across
IANA releases and jurisdictions. This tool uses the installed `zoneinfo` data
and Swiss Ephemeris' proleptic Gregorian calendar flag (`GREG_CAL`); for an
old civil record, independently verify the historical offset and whether the
local calendar had adopted Gregorian dating.

## Study transits

A transit report compares one moving sky moment with a fixed natal chart. The
natal can come from the saved chart library:

```bash
python -m sidereal transit \
  --natal "Me" --charts-dir charts \
  --date 2026-07-11 --time 12:00 --tz UTC \
  --db data/sidereal.db \
  --out reports/me-transit.json --md reports/me-transit.md \
  --svg reports/me-transit.svg
```

Or supply the natal moment inline without saving it:

```bash
python -m sidereal transit \
  --natal-date 2000-12-12 --natal-time 12:00 --natal-tz UTC \
  --natal-lat 0 --natal-lon 0 --natal-label "Inline natal" \
  --date 2026-07-11 --time 12:00 --tz UTC \
  --out reports/inline-transit.json --md reports/inline-transit.md
```

The transit date, civil time, and timezone are required. Transit latitude and
longitude are an optional pair; without them the moving chart stays
planet-only. Placements still show each moving body in its Midpoint sign, and
when the natal has known time and location they show which natal house the
moving body occupies. Relationships are moving-body-to-fixed-natal major
aspects with orb, applying/separating state, and the current interpretation DB
record. The transit Moon is always included and explicitly labeled
time-sensitive.

Because natal and transit moments have different ecliptic-of-date axes,
cross-time aspects and natal-house overlays compare their shared J2000
longitudes. Applying/separating uses the moving body's J2000 longitudinal
speed. This is distinct from ordinary within-one-chart aspects, where all
points already share that chart's tropical frame of date.

Omitting `--natal-time` on an inline natal preserves the unknown-time contract:
local noon is only the body-position convention, natal Ascendant/Midheaven and
houses remain absent, aspects to natal angles are omitted, and transit
placements receive no natal-house overlay. Transit reports describe geometric
correlations for symbolic study, not predictions, and do not declare one
zodiac uniquely true.

Same-body contacts such as moving Jupiter to natal Jupiter have their own
report subsection. The transit wheel uses separate natal and moving-sky lanes,
while retaining the natal Ascendant orientation and house cusps.

## Sky pack for Moon Chorus

Export the current moving sky, fixed natal glyphs, and major transit-to-natal
geometry as local-only `skypack_v2` JSON:

```bash
python -m sidereal skypack --natal bobby-19831129T132400Z-e1d0a0c471 \
  -o data/fixtures/skypack_bobby_sample.json
```

With no `--when` or `--tz`, the command uses the current instant and the saved
natal chart's timezone. The checked-in Bobby sample fixes the sky at
`2026-07-11T18:09:00+00:00`; regenerate that geometry with:

```bash
python -m sidereal skypack --natal bobby-19831129T132400Z-e1d0a0c471 \
  --when 2026-07-11T14:09:00 --tz America/New_York \
  --ephe-path data/ephe \
  -o data/fixtures/skypack_bobby_sample.json
```

`generated_at` records the regeneration time. Last-decimal positions can also
vary slightly when optional Swiss `.se1` files are absent and the documented
Moshier fallback answers instead; the epoch and schema remain fixed.

Version 2 adds `same_body_delta` (shortest-arc now-vs-natal values) and
`resonance_rank` (deterministic, tightest-first any-hit ordering) while keeping
the v1 geometry arrays. Every ranked resonance has a positive `orb_limit`;
missing or non-positive limits are rejected rather than guessed. Moon Chorus
may use theatre lighting, but glyph positions remain anchored to the real
`epoch_utc` J2000 longitudes.

The localhost API exposes the same pack:

```bash
curl --get http://127.0.0.1:8742/api/skypack \
  --data-urlencode natal_id=bobby-19831129T132400Z-e1d0a0c471 \
  --data-urlencode when=2026-07-11T14:09:00 \
  --data-urlencode tz=America/New_York
```

Packs are `local_only` and are consumed by aim-dojo's `?sky=clocked_chart`
mode; they are not leaderboard, share, or multiplayer payloads.

### Public sky-day API

`sky-day` is the natal-free public geometry counterpart to a personal sky
pack. It calculates all 12 configured movers at local noon on one civil date,
maps them through the same Midpoint boundaries and glyph helpers, and emits no
birth identifiers, natal ghosts, resonances, or relationship data:

```bash
python -m sidereal sky-day --tz UTC --date 2026-07-12 \
  -o /tmp/skyday.json
```

The web route has the same `skyday_v1` contract:

```bash
curl --get http://127.0.0.1:8742/api/sky-day \
  --data-urlencode tz=UTC \
  --data-urlencode date=2026-07-12
```

Omit `date` to use today in the requested timezone. An optional `when` accepts
a local or offset-aware ISO calculation instant; otherwise the representative
instant is local noon. The server caches the first complete response under the
independently selected `tz:YYYY-MM-DD` key, so later requests for that key
retain the same `generated_at`, epoch, and geometry even if they pass another
`when`. This cache is process-local and resets on restart; successful responses
also advertise `Cache-Control: public, max-age=3600`.

Cross-origin access is scoped to the sky surfaces: `/api/sky-day`,
`/api/sky-listen`, and authenticated `/api/me/*`. The built-in allowlist has
the Moon Chorus Vercel/GitHub origins and the two `:8931` development origins.
Merge additional exact origins with the comma-separated
`SKY_DAY_CORS_ORIGINS` environment variable. Legacy desk/report routes do not
inherit this CORS grant.

### Authenticated Save my sky API

Moon Chorus users may opt into one private natal record. These routes require
`Authorization: Bearer <supabase_access_token>` and derive `user_id` only from
the verified JWT subject:

| Method | Route | Result |
|--------|-------|--------|
| `POST` | `/api/me/natal` | Validate, calculate, and upsert the user's birth profile |
| `GET` | `/api/me/natal` | Return that user's normalized profile metadata |
| `DELETE` | `/api/me/natal` | Idempotently clear that user's profile |
| `GET` | `/api/me/skypack` | Return today's `user_private` natal-bearing skypack |
| `POST` | `/api/me/transit-essay` | Idempotently enqueue today's private whole-chart transit note |
| `GET` | `/api/me/transit-essay` | Return today's essay status or validated result |

Unknown or null birth time is normalized to `time_unknown: true` and stored as
null. Calculation uses local noon while retaining `time_known: false`, so no
houses or angles are invented. Personal skypacks are cached in-process by
user, timezone, and civil date; a profile edit/delete invalidates that user's
entries. Packs contain geometry and a neutral label, never date of birth,
coordinates, or place text.

Nonexistent local times during a DST jump are rejected. The v1 payload has no
fold selector for a repeated DST hour, so ambiguous local times are also
rejected rather than guessed; save the time as unknown when the occurrence
cannot be established unambiguously.

Railway/Supabase configuration:

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Project URL; also pins the accepted JWT issuer |
| `SUPABASE_JWT_SECRET` | Legacy/shared Supabase HS256 JWT secret used to verify access tokens |
| `SUPABASE_JWT_AUDIENCE` | Optional audience override; defaults to `authenticated` |
| `SUPABASE_SECRET_KEY` | Preferred current `sb_secret_*` server-only PostgREST credential |
| `SUPABASE_SERVICE_ROLE_KEY` | Legacy server-only JWT credential; fallback when no secret key is set |
| `SUPABASE_NATAL_TABLE` | Optional table override; defaults to `natal_charts` |
| `SIDEREAL_NATAL_BACKEND` | `auto`, `supabase`, or explicit volatile `memory` |
| `SIDEREAL_DEV_AUTH` | Set to `1` only locally to enable `X-Dev-User-Id` |

`auto` selects Supabase when its URL/server-key variables are complete and
otherwise uses process memory. Partial Supabase storage configuration fails at
startup instead of silently losing durable profiles. `SUPABASE_SECRET_KEY`
takes precedence when both server-key forms are present. Server keys are never
returned to or accepted from the browser. The expected `natal_charts`
columns are `user_id` (primary key), `birth_date`, nullable `birth_time`,
`time_unknown`, `tz`, nullable paired `lat`/`lon`, `place_label`, and
`updated_at`; enable owner-only RLS for direct user access even though this
server always filters by the verified subject.

Parcel P verifies legacy/shared-secret Supabase access tokens with pinned
HS256. Projects that have migrated Auth token signing to asymmetric keys need
a JWKS verifier before enabling these routes; configuring only a server API
key does not enable user authentication.

For a local disposable smoke test, start a memory backend with the explicit
development header escape hatch:

```bash
SIDEREAL_NATAL_BACKEND=memory SIDEREAL_DEV_AUTH=1 \
  python -m sidereal serve --db data/sidereal.db

curl -sS -X POST http://127.0.0.1:8742/api/me/natal \
  -H 'Content-Type: application/json' \
  -H 'X-Dev-User-Id: demo-user' \
  --data '{"birth_date":"1983-11-29","birth_time":null,"time_unknown":true,"tz":"Asia/Tokyo","lat":35.68,"lon":139.69,"place_label":"Tokyo, Japan"}'

curl -sS http://127.0.0.1:8742/api/me/skypack \
  -H 'X-Dev-User-Id: demo-user'
```

Never enable `SIDEREAL_DEV_AUTH` on Railway. Production calls use the Supabase
Bearer token instead.

### Personal transit essay API

For an authenticated user with a saved natal profile, the transit-essay API
computes the complete configured major transit-to-natal study for the current
instant and sends its facts to the server-side DeepSeek worker. The fact object
contains Midpoint placements, all movers, same-body J2000 deltas, and up to the
24 tightest normalized-orb aspects across multiple moving bodies. It does not
use the sphere's visibility or single-body Listen highlight filters, and it
never sends a user id, birth fields, place text, token, or API key to the model.

```bash
curl -sS -X POST http://127.0.0.1:8742/api/me/transit-essay \
  -H 'Authorization: Bearer <supabase_access_token>'

curl -sS http://127.0.0.1:8742/api/me/transit-essay \
  -H 'Authorization: Bearer <supabase_access_token>'
```

`POST` is idempotent for `(user, civil date in the natal timezone, natal
fingerprint)`: it returns `pending` while the background completion runs and
returns the cached `ready` record without another model call afterward. A new
civil day or changed natal geometry creates a new key. Clients should poll
`GET` every 8–15 seconds with backoff and stop after roughly 2–3 minutes.
Responses are always `private, no-store`; missing natal profiles return 404.
Without `DEEPSEEK_API_KEY`, both operations return `status: unavailable` and no
provider request is attempted.

Provider output must contain exactly `headline`, `body`, and at most five
`watchpoints`. The server rejects predictive, medical, financial, legal,
crisis, fate/guarantee language, HTML, and explicit aspects absent from the
ephemeris facts. Failures expose only a generic `failed` status. Ready responses
always include the epistemic footer “symbolic study notes, not predictions.”
The queue is process-local; when `SIDEREAL_DB` points to an existing persistent
volume database, pending/ready/failed rows are stored in the private
`personal_transit_essays` SQLite table and can survive deploys.

### Sky Listen API

The local desk can return a short symbolic placement note plus personal
transit context for a saved natal chart:

```bash
curl --get http://127.0.0.1:8742/api/sky-listen \
  --data-urlencode natal_id=bobby-19831129T132400Z-e1d0a0c471 \
  --data-urlencode body=pluto \
  --data-urlencode when=2026-07-11T14:09:00 \
  --data-urlencode tz=America/New_York
```

Omit `natal_id` for the generic placement block only; use `sign=libra` for a
constellation/sign Listen. When `natal_id` is omitted and a valid Bearer token
has a saved profile, the same endpoint composes `personal.available: true`
from that user's in-memory natal chart. A valid user with no saved chart still
gets the generic placement response. An invalid supplied token returns 401;
it never silently downgrades to anonymous. File-based `natal_id` remains the
backward-compatible local desk path and cannot be combined with Bearer auth.
Responses are symbolic study notes, not predictions.

## Transit vs two-person synastry

A **transit** compares the moving sky at one date with one fixed natal chart.
**Two-natal synastry** compares two fixed birth or event charts. They are
separate studies: neither mode produces compatibility scores, destiny claims,
or event predictions.

Compare two saved charts while preserving their A/B roles:

```bash
python -m sidereal synastry \
  --a "Me" --b "Partner" --charts-dir charts \
  --db data/sidereal.db \
  --out reports/me-partner.json --md reports/me-partner.md
```

Inline moments are also supported. Each side may independently omit its time;
that side then contributes planets but no Ascendant or Midheaven:

```bash
python -m sidereal synastry \
  --a-date 2000-12-12 --a-time 12:00 --a-tz UTC --a-lat 0 --a-lon 0 \
  --a-label "Chart A" \
  --b-date 1990-06-15 --b-tz UTC --b-label "Chart B" \
  --db data/sidereal.db \
  --out /tmp/synastry.json --md /tmp/synastry.md
```

Cross-chart aspects use the same configured major orbs and common J2000 frame
as transits. Applying/separating is intentionally unset because both charts are
fixed snapshots.

## Local web desk

The optional web interface is a same-origin shell over the existing Python
services:

```text
browser UI -> localhost FastAPI -> chart / transit / library / interpretation DB
```

There is no ephemeris or second calculation stack in JavaScript. Install the
web extra, initialize the DB as above, and start the server:

```bash
python -m pip install -e ".[web]"
python -m sidereal serve --db data/sidereal.db --charts-dir charts
# open http://127.0.0.1:8742/
```

The default bind is `127.0.0.1:8742`. Sidereal refuses a non-loopback host
unless exposure is explicit, for example
`--host 0.0.0.0 --allow-lan`. That flag can expose sensitive birth data and
saved charts to the local network. The new `/api/me/*` surface has Bearer
authentication, but legacy desk/report routes remain unauthenticated; the app
does not supply TLS or telemetry. Keep the default unless you have secured the
surrounding network yourself. LAN mode accepts numeric IP Host
headers; if you deliberately browse through a local DNS name, add that exact
name with repeatable `--trusted-host NAME`. Wildcards are refused so the Host
guard continues to block DNS-rebinding origins.

### Railway notes for public and personal sky

For a future isolated Railway instance, install the web extra and pass
Railway's port, public bind, and exact generated hostname explicitly:

```bash
python -m pip install ".[web]"
python -m sidereal serve --host 0.0.0.0 --allow-lan \
  --trusted-host "$RAILWAY_PUBLIC_DOMAIN" --port "$PORT"
```

- Set `SKY_DAY_CORS_ORIGINS` when the game uses an origin beyond the built-in
  allowlist.
- Configure the Supabase variables above for durable Save my sky. Do not set
  `SIDEREAL_DEV_AUTH` in a public environment.
- Set `SIDEREAL_EPHE_PATH` to a directory or mounted volume containing the
  Swiss `.se1` files. Without them, the documented Moshier fallback is used;
  strict Swiss mode should not be enabled until those files are present.
- `SIDEREAL_BOUNDARY_PATH` may override the packaged Midpoint boundary JSON.
- Use `/api/sky-day?tz=UTC` (or `/api/health`) as the health check. The day
  cache is in-memory per process and is intentionally rebuilt after restarts.
- Do not place legacy personal chart files in the public image. Authenticated
  natal rows stay in Supabase and are computed in memory; the wider legacy
  local-desk routes remain unauthenticated, so public deployments should not
  mount a private `charts/` directory.

The browser provides chart calculation and readable reports, a searchable
timezone/place picker, saved-chart library actions, current-DB
reinterpretation, transits to a selected saved natal, and two-saved-chart
synastry. Synastry studies can be saved under the gitignored
`charts/synastry/` directory, reopened locally, and refreshed from their linked
natal snapshots plus the current interpretation DB. Chart reports retain their
planets-in-houses tables and by-house readings; transit reports retain their
moving-planet-by-natal-house view.

Persistent synastry snapshots require two saved natal charts so every saved
study remains refreshable. Refresh refuses to write if the DB or either linked
natal is unavailable. Snapshot IDs are safe lowercase filename tokens;
colliding new labels receive a numeric suffix, while replacement is reserved
for the explicit refresh path.

Snapshot files use best-effort owner-only POSIX permissions in addition to the
localhost and gitignore boundaries. On WSL paths mounted from Windows (such as
`/mnt/c`), mode bits may still display as `0777`; Windows ACLs remain the actual
filesystem protection. Use a Linux-filesystem `--charts-dir` when meaningful
POSIX owner-only modes are required.
Natal and transit results show the Python-rendered wheel above the placement
tables. Its JSON API uses the same validation and calculation paths as the CLI:

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/api/health` | Version, ephemeris probe, DB availability, and saved-chart count |
| `GET` | `/api/sky-day` | Public, natal-free daily Midpoint body geometry |
| `GET` | `/api/sky-listen` | Public placement or authenticated personal transit Listen |
| `GET` | `/api/skypack` | Legacy local file-chart skypack export |
| `POST` / `GET` / `DELETE` | `/api/me/natal` | Authenticated private natal profile CRUD |
| `GET` | `/api/me/skypack` | Authenticated daily private skypack |
| `POST` / `GET` | `/api/me/transit-essay` | Async private daily whole-chart transit synthesis |
| `POST` | `/api/chart` | Calculate and compose a full chart report |
| `POST` | `/api/transit` | Run a saved-natal or inline-natal transit report |
| `POST` | `/api/synastry` | Compare two saved and/or inline fixed charts |
| `GET` | `/api/synastries` | List private local synastry snapshots |
| `GET` | `/api/synastries/{id}` | Open one saved synastry snapshot |
| `POST` | `/api/synastries/{id}/refresh` | Recompose a linked snapshot from natal geometry and the current DB |
| `GET` | `/api/charts` | List saved charts |
| `GET` | `/api/charts/{id}` | Read one frozen saved geometry record |
| `POST` | `/api/charts` | Calculate and save a chart locally |
| `POST` | `/api/charts/{id}/interpret` | Recompose saved geometry with the current DB |
| `GET` | `/api/db/gaps` | Audit all gaps or scope with `?chart_id=...` |
| `GET` | `/api/db/entry/{id}` | Read one interpretation record |

Interactive API documentation is available locally at `/api/docs` while the
server is running. After dependencies are installed, calculations and saved
data remain local and require no external runtime network access.

### Ophiuchus example

The canonical table defines Ophiuchus as J2000 ecliptic longitude
`[254.7132°, 267.0711°)`. A stable, central Sun fixture is:

```bash
python -m sidereal chart \
  --date 2000-12-12 --time 12:00 --tz UTC \
  --lat 0 --lon 0 \
  --out /tmp/ophiuchus.json --md /tmp/ophiuchus.md
```

That date is deliberately used instead of late November: under the published
boundary numbers, a J2000-era late-November Sun is still before the Ophiuchus
start. Boundary geometry takes precedence over a conventional date label.

## Calculation choices

- Zodiac: `midpoint_v1`, 13 unequal circular segments in the J2000 ecliptic
  frame; it is not Lahiri plus twelve 30° signs.
- Frame conversion: Swiss Ephemeris directly supplies both date and J2000
  coordinates for bodies. For Asc/MC/equal cusps, corresponding SE Cartesian
  body vectors recover the exact rigid date→J2000 rotation, which is applied
  to each tropical cusp individually; this avoids the invalid shortcut of
  recomputing "sidereal equal houses." Requested flags, actual backend,
  boundary hash/provenance, and effective chart configuration are retained in
  metadata. See `IMPLEMENTATION_NOTES.md` for validation details.
- Boundary blend: within 3° of either adjacent sign boundary by default.
- Houses: twelve equal 30° houses measured from the Ascendant, only when time
  and both coordinates are known. Each cusp is then mapped through Midpoint.
- Aspects: conjunction, opposition, trine, square, and sextile, with speeds
  used to mark applying/separating.
- Interpretation: stored in SQLite/JSON seeds, never hard-coded into the
  geometry engine. Stubs and absent records are visible gaps.
- Comparison: tropical labels map each stored `lon_date`; Midpoint labels stay
  on the primary J2000 geometry. Comparison never triggers a second DB reading.
- Saved charts: JSON snapshots under `charts/`, with calculation input/config
  and complete geometry for offline re-interpretation. Permissions are made
  owner-private on platforms that support POSIX modes; the user remains
  responsible for protecting the directory elsewhere.
- Transits: one current chart calculated by the primary engine against frozen
  natal geometry; natal-house overlays and natal-angle aspects exist only when
  natal time is known.
- Synastry: two fixed charts compared role-preservingly in their common J2000
  frame; applying/separating is not assigned and no compatibility score exists.
- Wheel: a pure SVG rendering of stored J2000 geometry, with unequal Midpoint
  arcs, Ophiuchus, optional houses, and an optional moving-sky overlay.
- Web: optional FastAPI adapter and static same-origin UI. It delegates to the
  chart, transit, synastry, wheel, library, and interpretation modules and
  binds to loopback by default.

## Validate the installation

```bash
python -m pytest
python -m sidereal db init --db data/sidereal.db
python -m sidereal db import --db data/sidereal.db
python -m sidereal db gaps --db data/sidereal.db
python -m sidereal chart \
  --date 2000-01-01 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --md /tmp/sidereal-smoke.md --out /tmp/sidereal-smoke.json \
  --svg /tmp/sidereal-smoke.svg
python -m sidereal save \
  --label "Smoke" --date 2000-12-12 --time 12:00 --tz UTC \
  --lat 0 --lon 0
python -m sidereal db gaps --db data/sidereal.db --chart-id "Smoke"
python -m sidereal transit \
  --natal "Smoke" --date 2026-07-11 --time 12:00 --tz UTC \
  --md /tmp/sidereal-transit.md --out /tmp/sidereal-transit.json \
  --svg /tmp/sidereal-transit.svg
python -m sidereal save \
  --label "Smoke Partner" --date 1990-06-15 --time 12:00 --tz UTC \
  --lat 0 --lon 0
python -m sidereal synastry --a "Smoke" --b "Smoke Partner" \
  --db data/sidereal.db \
  --md /tmp/sidereal-synastry.md --out /tmp/sidereal-synastry.json
python -m sidereal sky-day --tz UTC --date 2026-07-12 \
  -o /tmp/sidereal-skyday.json
# With .[web] installed, in another terminal:
python -m sidereal serve
# curl http://127.0.0.1:8742/api/health
```

Tests cover boundary invariants and wraparound, representative Midpoint
placements, time conversion, a real Swiss Ephemeris sanity value, equal
houses, aspect dynamics, unknown-time omission rules, inventory counts,
report gaps, tropical comparison frames, saved-chart round trips, CLI behavior,
scoped gap audits, same-body transit keys, transit role/orb and unknown-time
rules, two-natal J2000 synastry, deterministic SVG wheels, the local API and
browser UX contract, loopback binding safety, and installed-data discovery.

The repeatable Phase 5 CLI + test smoke is available as
`bash scripts/smoke_phase5.sh`; set `SIDEREAL_SMOKE_DIR` to choose the parent
for its fresh, per-run local artifact directory.

## Attribution and licensing

Midpoint boundaries follow Athen Chimenti's *The Midpoint Method: An
Ecliptic-Based Boundary System for Zodiacal Constellations*,
[Zenodo DOI 10.5281/zenodo.20747017](https://doi.org/10.5281/zenodo.20747017).
The source record was published June 18, 2026 under
[CC BY-NC-ND 4.0](https://creativecommons.org/licenses/by-nc-nd/4.0/). The
versioned data is in `data/boundaries/midpoint_j2000_v1.json`; preserve its
attribution and license metadata. No commercial interpretive prose is copied.

Swiss Ephemeris and `pyswisseph` have their own licensing terms, including the
Swiss Ephemeris dual-license model. Review the
[official license information](https://www.astro.com/swisseph/swephinfo_e.htm)
before distributing this project or ephemeris data. No project code license is
implied by this README.
