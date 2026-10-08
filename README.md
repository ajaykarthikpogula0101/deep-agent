# deependhq assistant

Cited Q&A over deependhq.com plus live Zoom demo booking. FastAPI + Postgres/pgvector, local Hugging Face
embeddings (bge-small via fastembed, no key), and any OpenAI-compatible chat model (Groq free tier by default).

## Run locally

```bash
cp .env.example .env            # fill LLM_API_KEY (Groq or OpenAI); use DATABASE_URL=...@127.0.0.1:5432/... outside Docker
docker compose up -d db          # pgvector
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (or .venv/bin/pip)
python -m app.ingest.pipeline    # crawl + embed locally (~1 minute, free; first run downloads the 130 MB model)
uvicorn app.main:app --port 8080 --reload
# open http://localhost:8080
```

Windows notes: use `127.0.0.1` rather than `localhost` in `DATABASE_URL` (Docker Desktop's IPv6 relay stalls), and
set `OPENBLAS_NUM_THREADS=1` if numpy complains about memory on a busy machine. Test-mode setup (your own Zoom
schedule and inbox instead of Deep's) is in `docs/TEST_SETUP.md`.

Or everything in Docker:

```bash
docker compose up --build -d
docker compose run --rm ingest
```

## Tests

```bash
pytest                      # 25 unit tests, no network, no DB
LIVE=1 pytest tests/test_live_zoom.py -s   # real schedules + availability from scheduler.zoom.us/sreedeep
python scripts/verify_zoom.py              # once Zoom S2S credentials are in .env (docs/ZOOM_SETUP.md)
```

## Embed on deependhq.com

```html
<script src="https://<assistant-host>/static/widget.js" defer></script>
```

Set `ALLOWED_ORIGINS=https://deependhq.com,https://www.deependhq.com` (no wildcard) and point the DNS
for `<assistant-host>` at the Cloud Run / App Runner service.

## Deploy (Cloud Run)

```bash
gcloud run deploy deependhq-assistant --source . --region asia-south1 \
  --set-env-vars-from-file .env.yaml --min-instances 1 --max-instances 2
```

`--min-instances 1` keeps the in-process re-crawl scheduler and rate limiter alive. Use Cloud SQL
(Postgres 16 + `vector` extension) or Neon for the database. App Runner/ECS: same image, same env.

## Layout

```
app/ingest     crawler (llms-full.txt, data.js, sitemap HTML) -> chunks -> embeddings
app/rag        retrieval with confidence floor, prompts, injection fences
app/booking    Zoom clients (official API + public fallback), tools, host brief email
app/security   rate limit + daily spend cap
app/chat.py    retrieve -> refuse/answer/book -> SSE stream
app/main.py    FastAPI, CORS allow-list, scheduler
static/        chat page + embeddable widget
docs/          PLAN.md, FAILURE_MODES.md, TEST_LOG.md
```

## Quickest local start (Windows)

Double-click `run.cmd` (or run `powershell -ExecutionPolicy Bypass -File scripts\run.ps1`). It starts Docker Desktop if it
is not running, waits for Postgres to be healthy, then starts the assistant on http://localhost:8080. Docker Desktop stops
whenever you sign out of Windows; the database container now has `restart: unless-stopped` and Docker Desktop is in the
Startup folder, so after a reboot both come back on their own. If you still see `connection to server at "127.0.0.1",
port 5432 failed`, Docker is not up yet: open it and wait for the whale icon to settle, or just run `run.cmd` again.
