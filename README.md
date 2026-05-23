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

## Deploy on Coolify

Use the **Dockerfile** build pack (recommended), or Nixpacks with the included `nixpacks.toml`.

1. Set environment variable `EDISON_API_KEY` in Coolify (do not rely on a `.env` file in the container).
2. **Leave the start command empty** — Coolify must not override with `bash -c` and a blank string (that causes `/bin/bash: -c: option requires an argument`).
3. Expose port `8765` (or set `PORT` to match your Coolify proxy).
4. Health check path: `/api/health`

If you must set a custom start command manually:

```bash
uvicorn server:app --host 0.0.0.0 --port ${PORT:-8765}
```
