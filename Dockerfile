# Public sidereal desk / sky-day API for Railway (Moon Chorus).
# Ephemeris files are fetched at build time (not in git).

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SIDEREAL_HOME=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install package (web extras = FastAPI + uvicorn)
COPY pyproject.toml README.md ./
COPY src ./src
COPY data/boundaries ./data/boundaries
COPY data/seeds ./data/seeds
COPY data/ephe/README.md ./data/ephe/README.md
COPY scripts/railway-start.sh ./scripts/railway-start.sh

RUN pip install --upgrade pip \
    && pip install -e ".[web]" \
    && chmod +x scripts/railway-start.sh

# Official Swiss Ephemeris planet + Moon files (1800–2399); gitignored locally, pulled here for deploy
RUN mkdir -p data/ephe charts data/cache/skyday \
    && curl -fsSL -o data/ephe/sepl_18.se1 \
         https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/sepl_18.se1 \
    && curl -fsSL -o data/ephe/semo_18.se1 \
         https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/semo_18.se1 \
    && test -s data/ephe/sepl_18.se1 && test -s data/ephe/semo_18.se1

# Optional interpretation DB so non-sky routes degrade cleanly; sky-day does not need seeds
RUN python -m sidereal db init --db data/sidereal.db \
    && python -m sidereal db import --db data/sidereal.db data/seeds \
    || true

EXPOSE 8742

# Railway injects PORT; start script binds 0.0.0.0 + --allow-lan
CMD ["./scripts/railway-start.sh"]
