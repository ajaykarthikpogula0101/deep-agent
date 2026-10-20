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

## Non-technical installs: the Windows bundle

Deep's end users are not technical (no Python, no terminal, no `.env`). So the one action became a zip:

```
python scripts/build_bundle.py        # -> dist/Robin-win64.zip
```

The bundle holds an embeddable CPython 3.11, every runtime requirement pre-installed, the app, the prebuilt
widget, `.env.example`, `Start Robin.bat` and a one-page `README.txt`. The user unzips it and double-clicks
`Start Robin.bat`:

1. `app.launch` starts the embedded database and the server
2. the browser opens **`/setup`**: website, name, short name, email, booking link, AI provider + key
   (or "no key yet" = quoted-text mode). Local-only; gone once `data/setup_done` exists
3. saving writes `.env`, applies the values to the running process and crawls the site in the background
   (`/setup/progress` shows it, then a button opens Robin)
4. next time, `Start Robin.bat` opens Robin directly

Crawler changes for ordinary websites: `llms-full.txt` and `data.js` are now optional (deependhq.com extras),
a missing `sitemap.xml` falls back to the homepage and the same-site pages it links to (capped at 60), and HTML
served in place of those files is ignored instead of crashing the first crawl.

### Bundle acceptance (20 Oct 2026, evening)

Build: `python scripts/build_bundle.py` → 198 s, **282 MB unzipped / 97 MB zip**, bundled interpreter imports
the app with the repo off `sys.path`. Test as a user: unzip into `C:\Users\…\r1\user\` (a normal, long
path), run exactly what `Start Robin.bat` runs, no browser:

| Step | Result | Time |
|---|---|---|
| Unzip (PowerShell `Expand-Archive`, 10,847 files) | ok | 172 s |
| First start | `.env` created, embedded Postgres ready (12.3 s), quoted-text mode announced, browser target `/setup` | 17 s to the setup page |
| `/setup` | 200, six fields; saved with site = deependhq.com, no AI key → 303 to `/setup/progress` | |
| First crawl | 150 pages, 223 passages, crawl 38.7 s; about 5 min overall because the 130 MB embedding model downloads first | |
| After setup | `.env` holds the site, origins, host email, empty key; `/site` 200; `/setup` redirects away (configured) | |
| "How do I get in touch?" | `degraded` + the configured contact route + hand-over offer, no blog citation | |
| Restart | embedded DB reused (0.0 s), "knowledge base present (150 pages)", opens `/site` | 6 s |

Evidence: `r1/bundle_evidence/run1.log`, `setup_form.html`, `chat1.sse`, `run2.log`.

## Round 3: shipping to non-technical users (20 Oct, late)

| Ask | Done | How |
|---|---|---|
| 1. Pre-bundled embedding model | yes | `build_bundle.py` downloads the model into `models/`; `Start Robin.bat`, `Robin.exe`, `start-robin.sh` and `app.launch` set `FASTEMBED_CACHE_PATH` + `HF_HUB_OFFLINE=1`, so the first crawl never contacts the hub (model loads in 2 s on Linux) |
| 2. Signed `Robin.exe` | half | `Robin.exe` is compiled at build time from `scripts/bundle/Robin.cs` (csc.exe ships with .NET Framework); `scripts/bundle/sign.ps1` signs it, `python.exe` and `update.ps1` with signtool once Champions has a code-signing certificate (`-Pfx` or `-Thumbprint`). **Unsigned until then: SmartScreen still warns.** |
| 3. Mac/Linux bundles | Linux yes, macOS untested | `--platform linux-x64 \| macos-arm64 \| macos-x64`: portable CPython (python-build-standalone) + wheels pip resolves for that platform from this machine, packed as `.tar.gz` with exec bits; `start-robin.sh`, `update.sh`. Linux x64 verified in WSL; macOS builds but no Mac to test |
| 4. Updates | yes | `build_bundle.py` writes `manifest.json` (version, archive, sha256) next to the archive; `Update Robin.bat` / `update.sh` read `UPDATE_URL` from `.env`, compare with `VERSION`, download, verify sha256, stop a leftover embedded Postgres, swap folders by rename, keep `.env` + `data/` |
| 5. Central AI key | yes | `--llm-key-file` writes the key into the bundle's `.env.example`; the setup page then says "AI answers are included" and asks nothing (a user may still paste their own). Ship a spend-capped key: anything inside a zip can be read out |

Also fixed on the way, found by the acceptance runs:
- The crawler's `llms-full.txt` / `data.js` / `sitemap.xml` were mandatory → optional, with a homepage-links fallback.
- Closing the Robin window left `postgres.exe` running (18 orphans after a day of testing), which later blocked
  the updater and half-deleted `python\`. `app.launch` now stops the embedded database on Ctrl+C, window close,
  log-off and shutdown; the updater stops any leftover and swaps by rename so a locked file can't brick an install.
- Chat without an `Origin` header (curl, scripts) was rejected on the Linux bundle: the "is this a local
  install" check only knew `@localhost` URLs, not pgserver's unix socket. `ROBIN_EMBEDDED_DB` now marks it.
- Quoted-text contact answer printed "book a call at  or email …" when no booking link was set.

Measured: Windows bundle 417 MB unzipped / 219 MB zip (model ~130 MB barely compresses), build 185 s.
Linux bundle 724 MB / 246 MB, build 208 s.

### Round 3 acceptance, Windows (21 Oct, rebuilt zip, fresh unzip into a user path)

| Step | Result | Time |
|---|---|---|
| `Robin.exe --no-browser` from nothing | `.env` created, embedded Postgres ready (11.7 s), setup page served | 18 s |
| `/setup` saved (no AI key) → first crawl | 150 pages / 223 passages, **35 s** with the pre-bundled model, no hub contact | 35 s (was ~5 min) |
| Server killed hard (simulates closing the window on an older build) | 6 `postgres.exe` left running | |
| `Update Robin.bat` against a local manifest | stopped the 6 leftovers, downloaded 219 MB, sha256 verified, folders swapped by rename, `.env` + `data/` kept | 298 s (local download + unzip) |
| Restart after update | embedded Postgres reused (0.3 s), 150 pages present | 5 s |

Note: my first acceptance runs reported "crawl done after ~310 s" on every platform; that was the test's
own polling bug (it waited for `"done": true` with a space; the JSON is compact). The crawl itself is
35–40 s on Windows and 44–88 s on WSL.

### Round 3 acceptance, Linux x64 (21 Oct, WSL Kali, final tar.gz)

| Step | Result | Time |
|---|---|---|
| `tar -xzf` as a normal user | 12,283 files, exec bits intact, bundled Python 3.11.17 imports the app | 11 s |
| `./start-robin.sh --no-browser` from nothing | embedded Postgres ready (3.5 s), setup page served | 18 s |
| `/setup` saved → first crawl | 150 pages / 223 passages, **offline** (pre-bundled model, no hub contact) | 47 s |
| "How do I get in touch?" | `degraded` + "You can email Deep at …" (no booking link was set, so no blank) | |
| Restart | embedded Postgres reused, 150 pages present | 16 s |

Found on the way: the first Linux archive carried the model cache's symlinks with Windows-style targets
(`..\..\blobs\…`), dead on Linux (`NO_SUCHFILE`). The tar is now written with `dereference=True`, which
stores real files; the archive grew to 307 MB because the model then exists under both `blobs/` and
`snapshots/` (pruning `blobs/` is the next size win). Linux archive: 724 MB unpacked / 307 MB tar.gz.

### Not done / remaining manual steps

- **Code signing certificate** (Champions): until then every download warns once in SmartScreen.
- **macOS**: builds, untested; needs a Mac for one acceptance run (and Gatekeeper notarisation, same story as signing).
- **Update hosting**: the manifest + archive need a static HTTPS location (S3, GitHub Releases on a public repo,
  or a folder on deependhq.com); `UPDATE_URL` in the shipped `.env.example` then points at it.
- **Bundle size**: 219 MB zip. Dropping the local embedding stack (`EMBED_PROVIDER=api` by default) would cut
  ~200 MB but needs an embeddings endpoint and a central key.
- CORS origins from `/setup` apply on the next start; embedding the widget on the real site needs one restart.

- `pgserver` is in the runtime requirements, so the Docker image grows by 41 MB; a split extra would avoid that.
- `fastembed`/`onnxruntime` remain in the runtime install; making them an extra needs `EMBED_PROVIDER=api` to
  become the default, which changes the live index.
- A screen recording of fresh start → ask → cite → stop → restart was not produced; the logs and SSE captures
  in `r1/r2_evidence/` are the evidence.
