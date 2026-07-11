#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
SMOKE_DIR="${SIDEREAL_SMOKE_DIR:-/tmp/sidereal-phase4-smoke}"
DB_PATH="${SMOKE_DIR}/sidereal.db"
CHARTS_DIR="${SMOKE_DIR}/charts"

cd "${ROOT_DIR}"
mkdir -p "${SMOKE_DIR}"

"${PYTHON_BIN}" -m sidereal db init --db "${DB_PATH}"
"${PYTHON_BIN}" -m sidereal db import --db "${DB_PATH}"
"${PYTHON_BIN}" -m sidereal db gaps --db "${DB_PATH}" |
  "${PYTHON_BIN}" -c 'import json, sys; p=json.load(sys.stdin); assert (p["ready"], p["stub"], p["missing"]) == (746, 166, 0); print("inventory: 746 ready / 166 stub / 0 missing")'

"${PYTHON_BIN}" -m sidereal chart \
  --date 2000-12-12 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --compare tropical --db "${DB_PATH}" \
  --out "${SMOKE_DIR}/chart.json" --md "${SMOKE_DIR}/chart.md"
"${PYTHON_BIN}" -m sidereal db gaps --db "${DB_PATH}" \
  --chart "${SMOKE_DIR}/chart.json" >/dev/null

"${PYTHON_BIN}" -m sidereal save \
  --label "Phase 4 Smoke" --date 2000-12-12 --time 12:00 --tz UTC \
  --lat 0 --lon 0 --charts-dir "${CHARTS_DIR}" >/dev/null
"${PYTHON_BIN}" -m sidereal transit \
  --natal "Phase 4 Smoke" --date 2026-07-11 --time 12:00 --tz UTC \
  --db "${DB_PATH}" --charts-dir "${CHARTS_DIR}" \
  --out "${SMOKE_DIR}/transit.json" --md "${SMOKE_DIR}/transit.md"
"${PYTHON_BIN}" -m sidereal db gaps --db "${DB_PATH}" \
  --chart "${SMOKE_DIR}/transit.json" >/dev/null

"${PYTHON_BIN}" -m pytest -q
printf 'Phase 4 smoke passed. Local artifacts: %s\n' "${SMOKE_DIR}"
