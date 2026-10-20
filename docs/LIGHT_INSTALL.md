# Light install (ChampRobin checklist R1–R5, 20 Oct 2026)

Goal from Deep's brief: one obvious action installs and starts the assistant on a single machine, with no
separately installed Postgres or Redis, intelligence kept behind APIs, existing deployments untouched.

## R1: before

Fresh clone of `main` (`7d94ad1`), Windows 11 Home 10.0.26300, Python 3.11.9, clean virtualenv.

| Step | Before | Notes |
|---|---|---|
| Prerequisites | Python 3.11, **Docker Desktop**, a chat-model API key | Docker only to run `pgvector/pgvector:pg16` |
| Manual commands to first answer | 6: copy `.env`, `docker compose up -d db`, venv, `pip install`, `python -m app.ingest.pipeline`, `uvicorn …` | plus editing `DATABASE_URL` from `@db` to `@127.0.0.1` when outside Docker |
| `pip install -r requirements.txt` | 113 s, 343 MB, 82 packages | ~200 MB is the local-embedding stack: sympy 79, onnxruntime 36, numpy 36+21, onnx 26 |
| Same install under a long project path | **fails**: `WinError 206 filename too long` inside `onnx` test data (134 s in) | Windows 260-char limit; a short path or long-path support is required |
| Separate services | Postgres + pgvector (Docker) | no Redis anywhere |
| Local model inference | embeddings via fastembed (130 MB download on first ingest, CPU) | chat already remote (OpenAI-compatible endpoint) |
| Dev tools in the end-user install | `pytest`, `pytest-asyncio`, `respx` | in `requirements.txt` |
| Widget | `static/widget.js`, `static/deep-assistant.js` committed prebuilt | **no Bun/Node needed** to run; `widget/` (React/Vue wrappers) and `tools/openui` (Node) are optional |
| Booking | Zoom API when credentials exist, else a prefilled hand-off link (`pending_zoom`) | never claims a booking without a provider |

Mismatch with the brief: it cites `backend/app/config.py` with SQLite, `mvp/run.sh`, a `Makefile` and a
"Lantern" booking seam. None exist in this repo (Postgres/pgvector only, `run.cmd` → `scripts/run.ps1`,
no Makefile, booking seam is `app/booking/`). The goals were applied; the file names were not.

## R2: one action

`run.cmd` (Windows) or `python -m app.launch` (any OS):

1. `.env` from `.env.example` if missing
2. widget assets present? port free? (actionable errors otherwise)
3. database: `DATABASE_URL` reachable → use it; set but unreachable → stop with the fix;
   unset / stock value → **embedded Postgres 16 + pgvector** via `pgserver` in `./data/pg`
4. schema (`init_schema`), crawl + embed on the first run only
5. server on `:8080`, browser opens the embed preview `/site`

`run.cmd` also creates `.venv` and installs the runtime requirements when missing. `run.cmd -Docker` is the
previous Docker path, unchanged. `docker-compose.yml` is unchanged.

Measured on a fresh clone (`C:\Users\…\r1\light`), nothing pre-installed: see "Acceptance run" below.

## R3: runtime vs developer tooling

| | Before | After |
|---|---|---|
| `requirements.txt` | 23 lines incl. pytest, pytest-asyncio, respx | 21 lines: those three moved to `requirements-dev.txt`; `pgserver==0.1.4` added |
| Install (short path) | 113 s, 343 MB, 82 packages | 110 s, 382 MB, 81 packages |
| Separately managed DB service | Docker Desktop (~1.5 GB) + pgvector image (~400 MB) | none |
| Still in the runtime install | fastembed + onnxruntime (local embeddings, the default) | same; `EMBED_PROVIDER=api` makes them unused but they are not yet an optional extra |

Limits, stated plainly: the embedded database is one Postgres process per install. One app instance, any
number of its threads: fine. Several app instances must share a real `DATABASE_URL`. Not a multi-instance
hosting answer.

## R4: intelligence stays behind APIs

- Chat: unchanged, remote (`LLM_BASE_URL` + `LLM_API_KEY`), key on the server only (`static/*.js` carry none).
- **No key → quoted-text mode** (`app/chat.py` step 4b): a `degraded` event, the sources, and the matching page
  text prefixed with a label; no model call, logged as `degraded`. Off-topic questions are still refused.
- **Timeout / rejected key** → `error: model_unavailable` + a labelled "having trouble answering" reply with
  the booking link and email (existing path, now covered by tests for both failures).
- **Embeddings**: `EMBED_PROVIDER=api` uses the OpenAI client against an `/embeddings` endpoint
  (`EMBED_BASE_URL`/`EMBED_API_KEY` default to the LLM ones, `EMBED_DIM` for unknown models). Default stays
  `local` so the live site keeps its 384-dim index; switching re-ingests. OpenRouter has no embeddings endpoint.
- Booking: unchanged; without Zoom credentials the chat offers the hand-off link and says `pending_zoom`.

Tests: `tests/test_light_install.py` (12): quoted-text mode with and without sources, timeout and auth
failure, the database rule (unset → embedded, stock Docker URL → embedded, reachable → used, explicit but
unreachable → stop), busy port, widget assets, API embeddings with and without a key.

## R5: proof

### Acceptance run (fresh clone, nothing pre-installed)

Fresh clone at `C:\Users\…\r1\light`, no `.env`, no `data/`, no model cache, `python -m app.launch --no-browser --port 8097`:

| Run | What happened | Time |
|---|---|---|
| 1, from nothing | `.env` created; embedded Postgres + pgvector ready (11.3 s); quoted-text mode announced (placeholder key); crawl + embed 150 pages / 223 chunks incl. the 130 MB model download (40.1 s); server up; `/site` → 200 | **59 s** to a serving assistant |
| ask | "How do I get in touch?" → `degraded` event, sources, labelled quoted text, `done`; database: 150 pages, 2 messages | |
| 2, restart | embedded Postgres reused (0.0 s); "knowledge base present (150 pages)", no re-ingest; server up | **7 s** |
| ask again | database: 150 pages, **4 messages**: chat history survived the restart | |

Logs and SSE captures: `r1/r2_evidence/run1.log`, `run1_chat.sse`, `run2.log`, `run2_chat.sse`.
Existing-deployment path: on the working clone, whose `.env` points at the Docker Postgres, the launcher used it
("using Postgres at 127.0.0.1:5432/assistant", "knowledge base present (145 pages)") and never touched `./data/pg`.

### Real-site check

"How do I get in touch?" against the freshly crawled deependhq.com content, no model key:

- First attempt (`run1_chat.sse`): quoted-text mode cited "Day 320 … delivery-partner account", a loosely
  related journey post. That is the failure the brief names, reproduced today, not an old report.
- Fix: in quoted-text mode a contact question gets the configured route instead of page text
  (`app/chat.py`, `_CONTACT_Q`). Re-run on the same fresh clone (`run3_chat.sse`):
  "You can book a call with Deep at https://scheduler.zoom.us/sreedeep or email deep@championsmail.com.
  (No AI model key is configured on this install, so this is the configured contact route, not a generated
  answer.)" followed by the hand-over offer. No sources, no blog citation.
- With a key, the model path already carries `prompts.contact_note` (the same route) in its system prompt.

Test suite on the branch: **599 passed, 1 skipped** (587 before + the 12 new tests), run from the working
clone against the Docker Postgres; `tests/test_live_zoom.py` excluded as usual.

### Not done / remaining manual steps

- `pgserver` is in the runtime requirements, so the Docker image grows by 41 MB; a split extra would avoid that.
- `fastembed`/`onnxruntime` remain in the runtime install; making them an extra needs `EMBED_PROVIDER=api` to
  become the default, which changes the live index.
- A screen recording of fresh start → ask → cite → stop → restart was not produced; the logs and SSE captures
  in `r1/r2_evidence/` are the evidence.
