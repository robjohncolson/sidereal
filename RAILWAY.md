# Deploy sidereal on Railway (public sky-day)

This service powers Moon Chorus **public** planet positions:

```text
GET https://<your-service>.up.railway.app/api/sky-day?tz=UTC
```

No birth data is required. Personal charts stay optional / local.

## One-time setup (Dashboard)

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
2. Select **`robjohncolson/sidereal`** (this repo).
3. Railway reads `Dockerfile` + `railway.toml`.
4. After first deploy, open **Settings → Networking → Generate Domain**.
5. Copy the public URL, e.g. `https://sidereal-production-xxxx.up.railway.app`.

### Variables (optional)

| Variable | Purpose |
|----------|---------|
| `SKY_DAY_CORS_ORIGINS` | Extra browser origins (comma-separated). Defaults already include `https://aim-dojo.vercel.app` and local `:8931`. |
| `SIDEREAL_TRUSTED_HOSTS` | Extra `Host` headers (custom domains), comma-separated. |
| `PORT` | Set by Railway automatically. |

`RAILWAY_PUBLIC_DOMAIN` is set by Railway; the start script passes it as `--trusted-host`.

## Point Moon Chorus at it

On the game (or local test):

```text
https://aim-dojo.vercel.app/?skyApi=https://<your-service>.up.railway.app
```

Or set in `index.html` / config:

```js
CFG.skyDay.api = 'https://<your-service>.up.railway.app'
// or leave default and use ?skyApi=
```

Hard-refresh after deploy. If the API is down, the game still shows sticks + Meeus ☉/☽ + glossary.

## CLI (local parity)

```bash
cd sidereal
. .venv/bin/activate
python -m pip install -e ".[web]"
python -m sidereal sky-day --tz UTC -o /tmp/skyday.json
python -m sidereal serve --host 0.0.0.0 --port 8742 --allow-lan \
  --ephe-path data/ephe --require-swiss-ephemeris \
  --db data/sidereal.db --trusted-host localhost
```

## Health

```bash
curl -s https://<your-service>.up.railway.app/api/health
curl -s --get https://<your-service>.up.railway.app/api/sky-day \
  --data-urlencode tz=UTC
```

Expect `type: "skyday"`, `privacy: "public"`, 12 movers.

## Notes

- Ephemeris files are **downloaded in the Docker build** (not stored in git).
- Interpretation seeds are imported at build for optional listen/desk routes.
- Empty `charts/` on Railway — no personal birth charts in the public image.
- Swiss Ephemeris license applies when redistributing data; see Astrodienst docs.
