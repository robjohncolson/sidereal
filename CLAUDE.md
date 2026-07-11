# Sidereal — agent guide

Local 13-sign Midpoint chart calculator and symbolic interpretation database.

## Authority and scope

1. `SPEC.md` is the product, calculation, content, and acceptance contract.
2. `CODEX_PROMPT.md` defines the required Phase 1 + Phase 2 delivery.
3. Keep astronomy/geometry reproducible and interpretations explicitly
   symbolic. Never move interpretive prose into the calculation engine.

Read the repository `AGENTS.md` before modifying code. In particular, run and
report GitNexus upstream impact before editing a symbol, warn before HIGH or
CRITICAL edits, and run GitNexus change detection before any commit. If the
shared index is stale, follow the repository owner's coordination instructions;
do not start concurrent analyzers.

## Defaults that must remain explicit

- Zodiac: `midpoint_v1`, thirteen unequal J2000 ecliptic segments including
  Ophiuchus; never model it as an ayanamsa plus 30° signs.
- Houses: `equal_house_12`, twelve 30° houses from Ascendant.
- Unknown time: calculate at explicit local noon, set `time_known=false`, and
  omit angles, houses, and angle aspects.
- Ambiguous IANA wall times: require `fold=0|1` / CLI `--fold 0|1`; reject
  nonexistent local times rather than silently shifting them.
- Boundary blend: 3°; aspects: modern majors.
- Geometry is valid without an interpretation database; missing/stub meanings
  must appear as report gaps.

## Local workflow

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
# Optional Swiss .se1 files (gitignored):
# curl -fL -o data/ephe/sepl_18.se1 https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/sepl_18.se1
# curl -fL -o data/ephe/semo_18.se1 https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/semo_18.se1
python -m pytest
```

Smoke test:

```bash
python -m sidereal db init --db data/sidereal.db
python -m sidereal db import --db data/sidereal.db
python -m sidereal chart \
  --date 2000-01-01 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --out /tmp/sidereal.json --md /tmp/sidereal.md
```

Seeds: `seed_0` inventory stubs · `seed_1` core primers (76) · `seed_2`
personal-planet major aspects (105). Regenerate with
`python -m sidereal.interpret.generate_seeds`.

Use `2000-12-12 12:00 UTC` for the central Ophiuchus Sun fixture. Under the
canonical J2000 Midpoint table (`254.7132°`–`267.0711°`), a J2000-era
**late-November** Sun is still in Scorpio — December ~7–18 is the Ophiuchus
window for that epoch. Geometry beats marketing date labels.

## Module boundaries

- `timebase.py`, `ephemeris.py`, `zodiac/`, `houses.py`, `aspects.py`: pure or
  thin geometry services.
- `chart.py`: orchestration only.
- `interpret/`: SQLite schema/store, inventory/seeds, and report composition.
- `cli.py`: argument validation and adapters; keep heavyweight imports local.
- Root `data/boundaries/` and `data/seeds/` are installed under
  `share/sidereal/`; runtime resolvers must work outside the repository cwd.

Preserve frozen public dataclasses, deterministic IDs/JSON, parameterized SQL,
explicit errors for wrong frames or incomplete coordinate pairs, and tests for
every unknown-time omission rule. Do not commit generated databases, reports,
charts, virtual environments, or `.se1` binaries.
