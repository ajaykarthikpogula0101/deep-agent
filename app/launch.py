"""One-action local start: ``python -m app.launch`` (``run.cmd`` on Windows).

Order: .env -> database -> schema -> first-run ingest -> server -> embed preview.

Database rule, so an existing deployment is never touched:
  * ``DATABASE_URL`` set in the environment or .env and reachable  -> use it.
  * set but unreachable                                             -> stop with the fix (no silent switch).
  * unset (or the stock default) and nothing listening there        -> embedded Postgres + pgvector
    via ``pgserver`` in ``./data/pg``. The data dir persists, so site data and
    chat history survive restarts and repeat installs.

Every failure names what to do. ``--port``, ``--no-browser``, ``--skip-ingest``.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "pg"
# Values that mean "nobody configured a database": the settings default and the
# Docker-compose URL that .env.example ships with.
STOCK_DEFAULT_URLS = {
    "postgresql://assistant:assistant@127.0.0.1:5432/assistant",
    "postgresql://assistant:assistant@localhost:5432/assistant",
    "postgresql://assistant:assistant@db:5432/assistant",
}
WIDGET_ASSETS = ("static/widget.js", "static/deep-assistant.js")


def fail(msg: str, code: int = 2) -> None:
    print(f"\n[launch] {msg}", file=sys.stderr)
    sys.exit(code)


def say(msg: str) -> None:
    print(f"[launch] {msg}", flush=True)


def dotenv_value(key: str) -> str:
    env = ROOT / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(f"{key}="):
            return s.split("=", 1)[1].split("#", 1)[0].strip().strip('"').strip("'")
    return ""


def ensure_env_file() -> bool:
    """Create .env from .env.example when missing. Returns True when it was created now (a brand-new install)."""
    env = ROOT / ".env"
    if env.exists():
        return False
    shutil.copy(ROOT / ".env.example", env)
    say("created .env from .env.example")
    return True


def ensure_widget_assets() -> None:
    missing = [a for a in WIDGET_ASSETS if not (ROOT / a).exists()]
    if missing:
        fail(f"widget assets missing: {', '.join(missing)}. They are committed prebuilt; "
             "restore them with `git checkout -- static/`. No Bun/Node is needed to run.")


def ensure_port_free(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            fail(f"port {port} is already in use. Stop the other server or run with --port {port + 1}.")


def reachable(url: str, timeout: float = 3.0) -> bool:
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=int(timeout)):
            return True
    except Exception:
        return False


def pick_database():
    """Return (url, embedded_server_or_None). See module docstring for the rule."""
    url = os.environ.get("DATABASE_URL") or dotenv_value("DATABASE_URL")
    explicit = bool(url) and url not in STOCK_DEFAULT_URLS
    if url and reachable(url):
        say(f"using Postgres at {url.split('@')[-1]}")
        return url, None
    if explicit:
        fail(f"DATABASE_URL is set ({url.split('@')[-1]}) but nothing answers there. Start that "
             "Postgres, fix the URL in .env, or remove DATABASE_URL to use the embedded database.")
    try:
        import pgserver
    except ImportError:
        fail("embedded database needs the `pgserver` package: run "
             "`pip install -r requirements.txt` in your virtualenv.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    server = pgserver.get_server(str(DATA_DIR))
    say(f"embedded Postgres + pgvector ready in {time.time() - t0:.1f}s (data: {DATA_DIR})")
    return server.get_uri(), server


def kb_pages() -> int:
    from app.db import conn, init_schema

    init_schema()
    with conn() as c:
        return c.execute("SELECT count(*) FROM pages").fetchone()[0]


def first_run_ingest(skip: bool, pages: int) -> None:
    from app.ingest.pipeline import run_ingest

    if pages:
        say(f"knowledge base present ({pages} pages); re-crawl runs on the RECRAWL_CRON schedule")
        return
    if skip:
        say("knowledge base empty and --skip-ingest given: answers will be empty until "
            "`python -m app.ingest.pipeline` runs")
        return
    say("first run: crawling and embedding the site (about a minute; the local embedding model "
        "downloads once, ~130 MB)")
    stats = run_ingest()
    say(f"ingest done: {stats}")


def open_when_ready(port: int, path: str = "/site") -> None:
    def _wait():
        for _ in range(120):
            time.sleep(0.5)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                continue
        else:
            return
        webbrowser.open(f"http://localhost:{port}{path}")

    threading.Thread(target=_wait, daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser(description="Start the assistant locally in one step.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--skip-ingest", action="store_true")
    args = ap.parse_args()

    os.chdir(ROOT)
    created_env = ensure_env_file()
    ensure_widget_assets()
    ensure_port_free(args.port)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")

    url, embedded = pick_database()
    os.environ["DATABASE_URL"] = url  # must be set before app.config is imported

    key = os.environ.get("LLM_API_KEY") or dotenv_value("LLM_API_KEY") or dotenv_value("OPENAI_API_KEY")
    if not key or key.endswith("..."):  # empty, or the .env.example placeholder
        os.environ["LLM_API_KEY"] = ""  # a placeholder must not reach the provider
        say("no LLM_API_KEY: the assistant runs in quoted-text mode (sources shown verbatim, no "
            "generated answers) until you add one to .env")

    from app.setup_page import mark_done, needs_setup

    pages = kb_pages()
    first_time = needs_setup() and (created_env or pages == 0)
    if first_time:
        # a brand-new install: the browser opens the setup page, which crawls the chosen site when saved
        say(f"first run: choose the website and your details at http://localhost:{args.port}/setup")
        landing = "/setup"
    else:
        if needs_setup():
            mark_done()  # an install configured by hand (.env + an existing knowledge base) never sees /setup
        first_run_ingest(args.skip_ingest, pages)
        landing = "/site"

    if not args.no_browser:
        open_when_ready(args.port, landing)
    say(f"starting on http://localhost:{args.port}  (opens {landing}; close this window or press Ctrl+C to stop)")
    import uvicorn

    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")
    finally:
        if embedded is not None:
            embedded.cleanup()
            say("embedded Postgres stopped; data kept in ./data/pg")


if __name__ == "__main__":
    main()
