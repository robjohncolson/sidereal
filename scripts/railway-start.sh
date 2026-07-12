#!/usr/bin/env bash
# Railway / public container entrypoint for sidereal serve.
set -euo pipefail

cd "${SIDEREAL_HOME:-/app}"

PORT="${PORT:-8742}"
HOST="${SIDEREAL_HOST:-0.0.0.0}"
EPHE_PATH="${SIDEREAL_EPHE_PATH:-data/ephe}"
DB_PATH="${SIDEREAL_DB:-data/sidereal.db}"
CHARTS_DIR="${SIDEREAL_CHARTS_DIR:-charts}"
BOUNDARY="${SIDEREAL_BOUNDARY_PATH:-data/boundaries/midpoint_j2000_v1.json}"

mkdir -p "$CHARTS_DIR" data/cache/skyday

if [[ ! -f "$DB_PATH" ]]; then
  echo "init interpretation db at $DB_PATH"
  python -m sidereal db init --db "$DB_PATH" || true
  if [[ -d data/seeds ]]; then
    python -m sidereal db import --db "$DB_PATH" data/seeds || true
  fi
fi

EXTRA=()
# Railway public hostname (exact Host header clients use)
if [[ -n "${RAILWAY_PUBLIC_DOMAIN:-}" ]]; then
  EXTRA+=(--trusted-host "$RAILWAY_PUBLIC_DOMAIN")
fi
# Comma-separated extra Host values (custom domains)
if [[ -n "${SIDEREAL_TRUSTED_HOSTS:-}" ]]; then
  IFS=',' read -ra _hosts <<< "$SIDEREAL_TRUSTED_HOSTS"
  for h in "${_hosts[@]}"; do
    h="$(echo "$h" | xargs)"
    [[ -n "$h" ]] && EXTRA+=(--trusted-host "$h")
  done
fi

echo "sidereal serve host=$HOST port=$PORT ephe=$EPHE_PATH trusted_extra=${#EXTRA[@]}"
exec python -m sidereal serve \
  --host "$HOST" \
  --port "$PORT" \
  --allow-lan \
  --ephe-path "$EPHE_PATH" \
  --require-swiss-ephemeris \
  --db "$DB_PATH" \
  --charts-dir "$CHARTS_DIR" \
  --boundary-path "$BOUNDARY" \
  "${EXTRA[@]}"
