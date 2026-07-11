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

Create an isolated environment and install the package:

```bash
python3 -m venv .venv
source .venv/bin/activate             # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m sidereal --help
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
| `seed_0_inventory_v1.json` | Full 912-key inventory as stubs |
| `seed_1_core_v1.json` | 76 ready primers (signs, houses, planets, Sun/Moon×sign, Asc×sign) |
| `seed_2_personal_aspects_v1.json` | 105 ready major aspects among Sun–Saturn |

After import: **181 ready**, **731 stubs**, **0 missing**. `gaps` audits the
complete inventory. `SIDEREAL_DB_PATH` changes the default `data/sidereal.db`
path. A chart still calculates if that database does not exist; its report
lists the interpretation keys as missing.

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
  --md /tmp/example.md
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

If both `--out` and `--md` are omitted, the full JSON report is printed to
stdout. Output parent directories are created when needed. Use `--no-houses`
to suppress houses even if time and coordinates are supplied.

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

## Validate the installation

```bash
python -m pytest
python -m sidereal chart \
  --date 2000-01-01 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --md /tmp/sidereal-smoke.md --out /tmp/sidereal-smoke.json
```

Tests cover boundary invariants and wraparound, representative Midpoint
placements, time conversion, a real Swiss Ephemeris sanity value, equal
houses, aspect dynamics, unknown-time omission rules, inventory counts,
report gaps, CLI behavior, and installed-data discovery.

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
