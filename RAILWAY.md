# Deploy sidereal on Railway (public sky + optional private natal)

This service powers Moon Chorus **public** planet positions:

```text
GET https://<your-service>.up.railway.app/api/sky-day?tz=UTC
```

No birth data is required for the public sky. Save my sky is optional and uses
authenticated Supabase-backed natal rows when the variables below are set.

## One-time setup (Dashboard)

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
2. Select **`robjohncolson/sidereal`** (this repo).
3. Railway reads `Dockerfile` + `railway.toml`.
4. After first deploy, open **Settings → Networking → Generate Domain**.
5. Copy the public URL, e.g. `https://sidereal-production-xxxx.up.railway.app`.

### Variables

| Variable | Purpose |
|----------|---------|
| `SKY_DAY_CORS_ORIGINS` | Extra browser origins (comma-separated). Defaults already include `https://aim-dojo.vercel.app` and local `:8931`. |
| `SIDEREAL_TRUSTED_HOSTS` | Extra `Host` headers (custom domains), comma-separated. |
| `PORT` | Set by Railway automatically. |
| `SUPABASE_URL` | Supabase project URL and JWT issuer base. |
| `SUPABASE_JWT_SECRET` | Legacy/shared Supabase HS256 JWT secret for access-token verification. |
| `SUPABASE_SECRET_KEY` | Preferred current `sb_secret_*` server key for owner-keyed `natal_charts` CRUD. |
| `SUPABASE_SERVICE_ROLE_KEY` | Legacy server-role JWT fallback when no secret key is set. |
| `SIDEREAL_NATAL_BACKEND` | Use `supabase` in production (`auto` is the default). |
| `SIDEREAL_DB` | Interpretation SQLite path; point this at a persistent Railway volume. |
| `DEEPSEEK_API_KEY` | Server-only key that enables shared missing/stub seed fills. |
| `DEEPSEEK_MODEL` | Optional model override; defaults to `deepseek-v4-flash`. |
| `DEEPSEEK_BASE_URL` | Optional API base; defaults to `https://api.deepseek.com`. |

`RAILWAY_PUBLIC_DOMAIN` is set by Railway; the start script passes it as `--trusted-host`.

This parcel pins user-token verification to HS256. If Supabase Auth uses
asymmetric signing keys, add JWKS verification before enabling the private
routes. Keep every server key out of browser configuration and logs.

For durable AI fills, attach a Railway volume and set, for example,
`SIDEREAL_DB=/data/sidereal.db`. The start script initializes/imports the
catalog only when that file is absent; later `ai-deepseek` entries remain in
the same database across deploys. Without `DEEPSEEK_API_KEY`, the Listen hook
does not start a worker.

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
- Interpretation seeds initialize the SQLite catalog; AI fills require a
  persistent `SIDEREAL_DB` volume to survive deploys.
- Keep `charts/` empty on Railway. Authenticated natal metadata stays in
  Supabase and private chart geometry is computed in memory.
- Never set `SIDEREAL_DEV_AUTH=1` on Railway.
- Swiss Ephemeris license applies when redistributing data; see Astrodienst docs.
