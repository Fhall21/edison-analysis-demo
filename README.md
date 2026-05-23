# Edison Data Analysis Demo

Standalone browser demo: upload CSVs (or use bundled sample HR data), ask a research question, and view Edison analysis results with live notebook cells and downloadable artifacts.

**Requires:** Python 3.11+ and an [Edison API key](https://platform.edisonscientific.com/profile).

## Quick start

```bash
cd projects_to_learn_from/repos/edison_analysis_demo
cp .env.example .env
# Edit .env — set EDISON_API_KEY=...

./run.sh
```

Open http://127.0.0.1:8765

Click **Use sample HR data** to analyze the bundled `sample_data/` CSVs (7 org HR files), or upload your own.

Alternatively: `make install` then `make run`.

If you add or change `EDISON_API_KEY` in `.env`, refresh the browser — no server restart needed.

Analysis typically takes 2–5 minutes; the UI polls every 5 seconds.

## Docker Compose (Coolify)

Use the **Docker Compose** build pack in Coolify. The compose file is the single source of truth — configure env vars there or in Coolify’s UI (they are detected automatically).

1. **Build pack:** Docker Compose  
2. **Docker Compose location:** `docker-compose.yml`  
3. **Environment variables** (required in Coolify):
   - `EDISON_API_KEY` — your Edison API key
   - `PORT` — defaults to `8765` if unset
4. **Domain:** assign a domain to the `edison-analysis-demo` service with container port **8765** (e.g. `https://analysis.example.com:8765` in Coolify’s domain field).
5. **Do not** set a custom start command in Coolify — the Dockerfile `CMD` handles it.
6. **Do not** add custom `networks:` or host `ports:` in the compose file; Coolify’s proxy routes traffic. Host port mapping bypasses the proxy and is only for local dev (see override example below).

Health check: `/api/health` (defined in compose + Dockerfile).

### Local Docker Compose

Create `.env` with `EDISON_API_KEY`, then either:

```bash
docker compose up --build
```

(without host access — useful for smoke tests), or publish locally:

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up --build
```

Open http://127.0.0.1:8765

## Deploy on Coolify (Dockerfile only)

Alternatively use the **Dockerfile** build pack instead of Docker Compose:

1. Set environment variable `EDISON_API_KEY` in Coolify (do not rely on a `.env` file in the container).
2. **Leave the start command empty** — Coolify must not override with `bash -c` and a blank string (that causes `/bin/bash: -c: option requires an argument`).
3. Expose port `8765` (or set `PORT` to match your Coolify proxy).
4. Health check path: `/api/health`

If you must set a custom start command manually:

```bash
uvicorn server:app --host 0.0.0.0 --port ${PORT:-8765}
```
