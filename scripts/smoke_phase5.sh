#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-python}"
SMOKE_PARENT="${SIDEREAL_SMOKE_DIR:-/tmp/sidereal-phase5-smoke}"

mkdir -p "${SMOKE_PARENT}"
SMOKE_DIR="$(mktemp -d "${SMOKE_PARENT%/}/run.XXXXXX")"
DB_PATH="${SMOKE_DIR}/sidereal.db"
CHARTS_DIR="${SMOKE_DIR}/charts"

cd "${ROOT_DIR}"

"${PYTHON_BIN}" -m sidereal db init --db "${DB_PATH}"
"${PYTHON_BIN}" -m sidereal db import --db "${DB_PATH}"
"${PYTHON_BIN}" -m sidereal db gaps --db "${DB_PATH}" |
  "${PYTHON_BIN}" -c 'import json, sys; p=json.load(sys.stdin); assert (p["ready"], p["stub"], p["missing"]) == (897, 70, 0); print("inventory: 897 ready / 70 stub / 0 missing")'
"${PYTHON_BIN}" -m sidereal db get \
  aspect:jupiter:sextile:jupiter --db "${DB_PATH}" |
  "${PYTHON_BIN}" -c 'import json, sys; p=json.load(sys.stdin); assert p["status"] == "ready"; print("Seed 6 Jupiter self-aspect: ready")'

"${PYTHON_BIN}" -m sidereal chart \
  --date 2000-12-12 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --compare tropical --db "${DB_PATH}" \
  --out "${SMOKE_DIR}/chart.json" --md "${SMOKE_DIR}/chart.md" \
  --svg "${SMOKE_DIR}/chart.svg"
"${PYTHON_BIN}" -c 'from pathlib import Path; from xml.etree import ElementTree as ET; path=Path("'"${SMOKE_DIR}"'/chart.svg"); root=ET.parse(path).getroot(); groups=[x for x in root.iter() if "sign-segment" in x.get("class", "").split()]; assert len(groups) == 13; assert "Ophiuchus" in path.read_text(); print("natal wheel: 13 signs including Ophiuchus")'

"${PYTHON_BIN}" -m sidereal save \
  --label "Phase 5 A" --date 2000-12-12 --time 12:00 --tz UTC \
  --lat 0 --lon 0 --charts-dir "${CHARTS_DIR}" >/dev/null
"${PYTHON_BIN}" -m sidereal save \
  --label "Phase 5 B" --date 1990-06-15 --time 12:00 --tz UTC \
  --lat 0 --lon 0 --charts-dir "${CHARTS_DIR}" >/dev/null

"${PYTHON_BIN}" -m sidereal transit \
  --natal "Phase 5 A" --date 2026-07-11 --time 12:00 --tz UTC \
  --db "${DB_PATH}" --charts-dir "${CHARTS_DIR}" \
  --out "${SMOKE_DIR}/transit.json" --md "${SMOKE_DIR}/transit.md" \
  --svg "${SMOKE_DIR}/transit.svg"
"${PYTHON_BIN}" -c 'import json; from pathlib import Path; p=json.loads(Path("'"${SMOKE_DIR}"'/transit.json").read_text()); assert p["report_type"] == "transit"; assert all(r["reading"]["status"] != "missing" for r in p["relationships"] if r["aspect"]["transit_body"] == r["aspect"]["natal_point"]); print("transit: sky↔natal self-hits resolved")'

"${PYTHON_BIN}" -m sidereal synastry \
  --a "Phase 5 A" --b "Phase 5 B" \
  --db "${DB_PATH}" --charts-dir "${CHARTS_DIR}" \
  --out "${SMOKE_DIR}/synastry.json" --md "${SMOKE_DIR}/synastry.md"
"${PYTHON_BIN}" -c 'import json; from pathlib import Path; p=json.loads(Path("'"${SMOKE_DIR}"'/synastry.json").read_text()); assert p["report_type"] == "synastry"; assert p["chart_a"]["label"] == "Phase 5 A"; assert p["chart_b"]["label"] == "Phase 5 B"; assert p["relationships"]; print("synastry: two saved charts compared")'

"${PYTHON_BIN}" -m pytest -q
if command -v node >/dev/null 2>&1; then
  node --check src/sidereal/web/static/app.js
  node tests/frontend_ux.test.js
fi

printf 'Phase 5 smoke passed. Local artifacts: %s\n' "${SMOKE_DIR}"
