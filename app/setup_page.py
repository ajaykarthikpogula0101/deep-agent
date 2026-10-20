"""First-run setup page for a non-technical install: GET/POST /setup.

Shown by app.launch on a brand-new install (no knowledge base yet). Only answers requests from the machine it
runs on and disappears once `data/setup_done` exists, so it is never reachable on a deployed site. Saving
writes the values to .env (keeping every other line), applies them to the running process, marks the install
as configured and crawls the chosen website in the background; /setup/status reports progress.
"""
from __future__ import annotations

import html
import logging
import re
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import settings

log = logging.getLogger("setup")
router = APIRouter()

ROOT = Path(__file__).resolve().parents[1]
MARKER = ROOT / "data" / "setup_done"
ENV_FILE = ROOT / ".env"

PROVIDERS = {  # key -> (base url, default chat model)
    "openrouter": ("https://openrouter.ai/api/v1", "openai/gpt-4.1-mini"),
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
    "openai": ("", "gpt-4.1-mini"),
    "none": ("", ""),
}
_state: dict = {"running": False, "done": False, "error": None, "stats": None}


def needs_setup() -> bool:
    return not MARKER.exists()


def mark_done() -> None:
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text("configured\n", encoding="utf-8")


def _local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def update_env(path: Path, values: dict[str, str]) -> None:
    """Set keys in a .env file in place: other lines, comments and order are kept."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        if m and m.group(1) in values:
            out.append(f"{m.group(1)}={values[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _origins(site: str) -> str:
    p = urlparse(site)
    host = p.netloc
    bare = host[4:] if host.startswith("www.") else host
    return ",".join(dict.fromkeys([f"{p.scheme}://{bare}", f"{p.scheme}://www.{bare}", "http://localhost:8080"]))


def _start_ingest() -> None:
    from app.ingest.pipeline import run_ingest

    def work():
        _state.update(running=True, done=False, error=None, stats=None)
        try:
            _state["stats"] = run_ingest()
        except Exception as e:
            log.exception("first crawl failed")
            _state["error"] = str(e)[:300]
        finally:
            _state.update(running=False, done=True)

    threading.Thread(target=work, name="first-ingest", daemon=True).start()


_PAGE = """<!doctype html><meta charset="utf-8"><title>Set up Robin</title>
<style>body{{font:15px/1.5 system-ui,Segoe UI,sans-serif;max-width:620px;margin:40px auto;padding:0 20px;color:#1a1f29}}
h1{{font-size:24px;margin:0 0 4px}} p.sub{{color:#5b6573;margin-top:0}} label{{display:block;margin:16px 0 4px;font-weight:600}}
input,select{{width:100%;padding:9px 10px;border:1px solid #c9d0d9;border-radius:6px;font:inherit;box-sizing:border-box}}
small{{color:#5b6573}} button{{margin-top:22px;padding:11px 18px;border:0;border-radius:6px;background:#1f3a5f;color:#fff;font:inherit;font-weight:600;cursor:pointer}}
.err{{background:#fde8e8;border:1px solid #f3b4b4;padding:10px 12px;border-radius:6px;margin:12px 0}}</style>
<h1>Set up Robin</h1><p class="sub">Five answers and Robin reads your website. You can change these later in the <code>.env</code> file.</p>
{error}
<form method="post" action="/setup">
<label>Website Robin should answer about</label><input name="site" value="{site}" placeholder="https://www.example.com" required>
<small>Robin reads the pages listed in the site's sitemap, or the homepage and the pages it links to.</small>
<label>Your name (as shown to visitors)</label><input name="host_full_name" value="{host_full_name}" required>
<label>Short name (how the assistant refers to you)</label><input name="host_name_short" value="{host_name_short}" required>
<label>Your email (visitors who ask to get in touch are told this)</label><input name="host_email" type="email" value="{host_email}" required>
<label>Booking link (Zoom scheduler, Calendly, ...; leave empty for none)</label><input name="booking" value="{booking}">
<label>AI provider</label><select name="provider">
<option value="openrouter" {p_openrouter}>OpenRouter</option><option value="groq" {p_groq}>Groq (free tier)</option>
<option value="openai" {p_openai}>OpenAI</option><option value="none" {p_none}>No AI key yet (quoted-text mode)</option></select>
<label>AI API key</label><input name="api_key" value="" placeholder="paste the key here (stays on this computer)">
<small>Without a key Robin shows the matching page text with its sources instead of written answers.</small>
<button type="submit">Save and read the website</button></form>"""

_PROGRESS = """<!doctype html><meta charset="utf-8"><title>Robin is reading your site</title>
<style>body{font:15px/1.5 system-ui,Segoe UI,sans-serif;max-width:620px;margin:40px auto;padding:0 20px;color:#1a1f29}
h1{font-size:24px} #s{padding:12px;border:1px solid #c9d0d9;border-radius:6px;background:#f6f8fb} a.btn{display:inline-block;margin-top:16px;padding:10px 16px;background:#1f3a5f;color:#fff;border-radius:6px;text-decoration:none}</style>
<h1>Reading your website…</h1><div id="s">Starting.</div><div id="next"></div>
<script>
async function tick(){const r=await fetch('/setup/status');const j=await r.json();const s=document.getElementById('s');
if(j.error){s.textContent='Could not read the site: '+j.error+'. Check the address and open /setup again.';return;}
if(j.done){s.textContent='Done: '+(j.stats?j.stats.pages_seen+' pages, '+j.stats.chunks_written+' passages.':'');
document.getElementById('next').innerHTML='<a class="btn" href="/site">Open Robin</a>';return;}
s.textContent='Working… this takes about a minute the first time.';setTimeout(tick,2000);}
tick();</script>"""


@router.get("/setup", response_class=HTMLResponse)
def setup_get(request: Request, error: str = ""):
    if not _local(request):
        return HTMLResponse("Setup is only available on the computer Robin runs on.", status_code=403)
    if not needs_setup():
        return RedirectResponse("/setup/progress" if _state["running"] or _state["done"] else "/site", status_code=303)
    cur = {"site": settings.site_base_url, "host_full_name": settings.host_full_name,
           "host_name_short": settings.host_name_short, "host_email": settings.host_email,
           "booking": settings.zoom_booking_base}
    page = _PAGE.format(error=f'<div class="err">{html.escape(error)}</div>' if error else "",
                        **{k: html.escape(v) for k, v in cur.items()},
                        **{f"p_{k}": ("selected" if k == "openrouter" else "") for k in PROVIDERS})
    return HTMLResponse(page)


@router.post("/setup")
def setup_post(request: Request, site: str = Form(...), host_full_name: str = Form(...), host_name_short: str = Form(...),
               host_email: str = Form(...), booking: str = Form(""), provider: str = Form("openrouter"),
               api_key: str = Form("")):
    if not _local(request):
        return HTMLResponse("Setup is only available on the computer Robin runs on.", status_code=403)
    if not needs_setup():
        return RedirectResponse("/site", status_code=303)
    site = site.strip().rstrip("/")
    if not site.startswith("http"):
        site = "https://" + site
    p = urlparse(site)
    if p.scheme not in ("http", "https") or not p.netloc or "." not in p.netloc:
        return RedirectResponse("/setup?error=Please+enter+the+website+address,+like+https://www.example.com", status_code=303)
    base_url, model = PROVIDERS.get(provider, PROVIDERS["openrouter"])
    api_key = api_key.strip()
    if provider == "none":
        api_key = ""
    values = {
        "SITE_BASE_URL": site, "ALLOWED_ORIGINS": _origins(site),
        "HOST_FULL_NAME": host_full_name.strip(), "HOST_NAME_SHORT": host_name_short.strip(),
        "HOST_EMAIL": host_email.strip(), "ZOOM_BOOKING_BASE": booking.strip(),
        "LLM_API_KEY": api_key, "LLM_BASE_URL": base_url, "CHAT_MODEL": model or settings.chat_model,
    }
    update_env(ENV_FILE, values)
    # apply to the running process (pydantic settings allow assignment); CORS origins apply on the next start
    settings.site_base_url = site
    settings.allowed_origins = values["ALLOWED_ORIGINS"]
    settings.host_full_name, settings.host_name_short = values["HOST_FULL_NAME"], values["HOST_NAME_SHORT"]
    settings.host_email, settings.zoom_booking_base = values["HOST_EMAIL"], values["ZOOM_BOOKING_BASE"]
    settings.llm_api_key, settings.llm_base_url, settings.chat_model = api_key, base_url, values["CHAT_MODEL"]
    mark_done()
    log.info("setup saved for %s (provider=%s, key=%s)", site, provider, "yes" if api_key else "no")
    _start_ingest()
    return RedirectResponse("/setup/progress", status_code=303)


@router.get("/setup/progress", response_class=HTMLResponse)
def setup_progress(request: Request):
    if not _local(request):
        return HTMLResponse("Setup is only available on the computer Robin runs on.", status_code=403)
    return HTMLResponse(_PROGRESS)


@router.get("/setup/status")
def setup_status(request: Request):
    if not _local(request):
        return JSONResponse({"error": "local only"}, status_code=403)
    return JSONResponse({"configured": not needs_setup(), **_state})
