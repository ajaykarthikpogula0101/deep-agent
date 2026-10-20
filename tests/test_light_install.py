"""Light install (app/launch.py) and the API-only intelligence rules (chat step 4b + provider failures).

No database, no model, no network: retrieval and embeddings are patched, the model client is a fake that fails
the way a real provider does, and the embedded database is a stub module.
"""
from __future__ import annotations

import json
import socket
import sys
import types
from unittest.mock import patch

import httpx
import pytest

from app import launch
from app.chat import DEGRADED_NOTE, respond
from app.config import settings
from app.rag.retrieve import Hit

VEC = [0.01] * 384


def _hit(score: float, title: str = "About Deep", text: str = "Deep builds in public at DeepEndHQ.",
         url: str = "https://deependhq.com/about") -> Hit:
    return Hit(url=url, title=title, section=None, text=text, score=score, metadata={})


def _collect(gen):
    return [json.loads(line[len("data: "):]) for line in gen if line.startswith("data: ")]


def _outcome(events):
    return [e for e in events if e.get("type") not in ("status", "lang", "meta")]


class _Failing:
    """An OpenAI-style client whose completion call raises like a provider would."""

    def __init__(self, exc: Exception):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
        self._exc = exc
        self.calls = 0

    def _create(self, **kwargs):
        self.calls += 1
        raise self._exc


# ---------------------------------------------------------------- chat: no key -> quoted text, never fake answers

@patch("app.chat.log_event")
@patch("app.chat.match_custom_answer", return_value=None)
@patch("app.chat.embed_query", return_value=VEC)
@patch("app.chat.search", return_value=[_hit(0.82), _hit(0.70, "Journey", "Day 300: shipped the assistant.",
                                                           url="https://deependhq.com/journey#day-300")])
def test_no_key_shows_quoted_sources_and_calls_no_model(search, embed, custom, log_event, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    client = _Failing(AssertionError("the model must not be called"))

    events = _outcome(_collect(respond("What does Deep do?", [], "Asia/Kolkata", "s-degraded", client=client)))

    assert events[0] == {"type": "degraded", "reason": "no_api_key"}
    assert events[1]["type"] == "sources" and events[1]["items"][0]["url"] == "https://deependhq.com/about"
    text = events[2]["text"]
    assert text.startswith(DEGRADED_NOTE)
    assert "[1] About Deep: Deep builds in public" in text and "[2] Journey:" in text
    assert events[-1] == {"type": "done"}
    assert client.calls == 0
    assert log_event.call_args_list[0][0][0] == "degraded"


@patch("app.chat.log_event")
@patch("app.chat.match_custom_answer", return_value=None)
@patch("app.chat.embed_query", return_value=VEC)
@patch("app.chat.search", return_value=[_hit(0.12)])
def test_no_key_and_no_sources_is_a_labelled_refusal(search, embed, custom, log_event, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")

    events = _outcome(_collect(respond("What's the weather in Paris?", [], "UTC", "s-degraded-2")))

    # an off-topic question is refused before the degraded branch, with no key involved
    assert events[0] == {"type": "refusal", "reason": "low_confidence"}
    assert events[-1] == {"type": "done"}


@patch("app.chat.log_event")
@patch("app.chat.match_custom_answer", return_value=None)
@patch("app.chat.embed_query", return_value=VEC)
@patch("app.chat.search", return_value=[_hit(0.80, "Day 320", "Restarted a delivery-partner account.")])
def test_no_key_contact_question_gives_the_contact_route_not_a_blog_post(search, embed, custom, log_event, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")

    events = _outcome(_collect(respond("How do I get in touch?", [], "Asia/Kolkata", "s-contact")))

    assert events[0] == {"type": "degraded", "reason": "no_api_key"}
    text = events[1]["text"]
    assert settings.zoom_booking_base in text and settings.host_email in text and "not a generated answer" in text
    assert "Day 320" not in text and all(e["type"] != "sources" for e in events)
    assert events[2] == {"type": "handover_offer"} and events[-1] == {"type": "done"}

    monkeypatch.setattr(settings, "zoom_booking_base", "")  # no booking link configured: email only, no blank
    text2 = _outcome(_collect(respond("How do I get in touch?", [], "Asia/Kolkata", "s-contact-2")))[1]["text"]
    assert text2.startswith(f"You can email {settings.host_name_short} at {settings.host_email}.")
    assert " at  " not in text2


# ---------------------------------------------------------------- chat: provider failures stay honest

@pytest.mark.parametrize("exc", [
    httpx.TimeoutException("timed out"),
    RuntimeError("401 Unauthorized: invalid api key"),
])
@patch("app.chat.log_event")
@patch("app.chat.match_custom_answer", return_value=None)
@patch("app.chat.embed_query", return_value=VEC)
@patch("app.chat.search", return_value=[_hit(0.82)])
def test_timeout_and_auth_failure_give_a_labelled_fallback(search, embed, custom, log_event, exc, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "key-present")
    client = _Failing(exc)

    events = _outcome(_collect(respond("What does Deep do?", [], "UTC", "s-fail", client=client)))

    assert client.calls == 1
    kinds = [e["type"] for e in events]
    assert "sources" in kinds and "error" in kinds and "degraded" not in kinds
    err = next(e for e in events if e["type"] == "error")
    assert err["error"] == "model_unavailable"
    fallback = events[kinds.index("error") + 1]["text"]
    assert "trouble answering" in fallback and settings.host_email in fallback
    assert events[-1] == {"type": "done"}
    assert any(c[0][0] == "error" for c in log_event.call_args_list)


# ---------------------------------------------------------------- launcher: database rule

def _fake_pgserver(calls: list):
    class Server:
        def get_uri(self):
            return "postgresql://postgres:@localhost:54329/postgres"

        def cleanup(self):
            calls.append("cleanup")

    def get_server(path):
        calls.append(("start", path))
        return Server()

    return types.SimpleNamespace(get_server=get_server)


def test_unset_database_url_uses_embedded_postgres(monkeypatch):
    calls: list = []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(launch, "dotenv_value", lambda key: "")
    monkeypatch.setattr(launch, "reachable", lambda url, timeout=3.0: False)
    monkeypatch.setitem(sys.modules, "pgserver", _fake_pgserver(calls))

    url, server = launch.pick_database()

    assert url.startswith("postgresql://") and ":54329/" in url
    assert server is not None and calls[0][0] == "start" and calls[0][1].endswith("pg")


def test_stock_default_url_falls_back_to_embedded_when_nothing_listens(monkeypatch):
    calls: list = []
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(launch, "dotenv_value",
                        lambda key: "postgresql://assistant:assistant@db:5432/assistant" if key == "DATABASE_URL" else "")
    monkeypatch.setattr(launch, "reachable", lambda url, timeout=3.0: False)
    monkeypatch.setitem(sys.modules, "pgserver", _fake_pgserver(calls))

    url, server = launch.pick_database()

    assert server is not None  # .env.example's Docker URL counts as "not configured"


def test_reachable_database_url_is_used_untouched(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@prod.internal:5432/assistant")
    monkeypatch.setattr(launch, "reachable", lambda url, timeout=3.0: True)
    monkeypatch.setitem(sys.modules, "pgserver", _fake_pgserver([]))

    url, server = launch.pick_database()

    assert url == "postgresql://u:p@prod.internal:5432/assistant" and server is None


def test_explicit_but_unreachable_database_url_stops_with_the_fix(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@prod.internal:5432/assistant")
    monkeypatch.setattr(launch, "reachable", lambda url, timeout=3.0: False)
    monkeypatch.setitem(sys.modules, "pgserver", _fake_pgserver([]))

    with pytest.raises(SystemExit) as exc:
        launch.pick_database()

    assert exc.value.code == 2
    assert "prod.internal" in capsys.readouterr().err  # never a silent switch to another database


def test_busy_port_is_an_actionable_error(capsys):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        with pytest.raises(SystemExit):
            launch.ensure_port_free(port)
    assert f"--port {port + 1}" in capsys.readouterr().err


def test_widget_assets_are_prebuilt_and_present():
    launch.ensure_widget_assets()  # no Bun/Node needed: the committed static files are the runtime


# ---------------------------------------------------------------- crawler: ordinary websites

def test_crawl_falls_back_to_homepage_links_on_a_site_without_agent_files(monkeypatch):
    import respx

    from app.ingest import sources

    monkeypatch.setattr(settings, "site_base_url", "https://www.example-shop.test")
    home = ('<html><title>Example Shop</title><body><main><h1>Example Shop</h1><p>' + "We sell widgets. " * 30
            + '</p><a href="/about">About</a> <a href="https://www.example-shop.test/pricing#top">Pricing</a> '
            '<a href="https://other.test/x">Other</a> <a href="/brochure.pdf">PDF</a></main></body></html>')
    page = '<html><title>About</title><body><main><p>' + "Founded in 1998 by two engineers. " * 20 + '</p></main></body></html>'
    with respx.mock(base_url="https://www.example-shop.test", assert_all_called=False) as m:
        m.get("/llms-full.txt").respond(404)
        m.get("/data.js").respond(404)
        m.get("/sitemap.xml").respond(404)
        m.get("/robots.txt").respond(404)
        m.get("/").respond(200, text=home)
        m.get("/about").respond(200, text=page)
        m.get("/pricing").respond(200, text=page)
        docs = sources.fetch_all_docs()

    urls = [d.url for d in docs]
    assert urls == ["https://www.example-shop.test/", "https://www.example-shop.test/about",
                    "https://www.example-shop.test/pricing"]
    assert all(d.source == "html" for d in docs)


def test_crawl_ignores_html_served_in_place_of_agent_files(monkeypatch):
    import respx

    from app.ingest import sources

    monkeypatch.setattr(settings, "site_base_url", "https://spa.test")
    with respx.mock(base_url="https://spa.test", assert_all_called=False) as m:
        m.get("/llms-full.txt").respond(200, text="<html>not ours</html>", headers={"content-type": "text/html"})
        m.get("/data.js").respond(200, text="<html>not ours</html>", headers={"content-type": "text/html"})
        with sources._client() as c:
            assert sources.docs_from_llms_full(c) == [] and sources.docs_from_data_js(c) == []


# ---------------------------------------------------------------- first-run setup page

@pytest.fixture
def setup_env(tmp_path, monkeypatch):
    from app import setup_page

    monkeypatch.setattr(setup_page, "MARKER", tmp_path / "data" / "setup_done")
    monkeypatch.setattr(setup_page, "ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env").write_text("# keep me\nLLM_API_KEY=sk-or-v1-...\nSITE_BASE_URL=https://deependhq.com\n", encoding="utf-8")
    started: list = []
    monkeypatch.setattr(setup_page, "_start_ingest", lambda: started.append(True))
    for k in ("site_base_url", "host_full_name", "host_name_short", "host_email", "zoom_booking_base",
              "llm_api_key", "llm_base_url", "chat_model", "allowed_origins"):
        monkeypatch.setattr(settings, k, getattr(settings, k))  # restored after the test
    return tmp_path, started


def _client(monkeypatch, local: bool):
    """The app under TestClient; `local` stands in for the request coming from 127.0.0.1 or not."""
    from fastapi.testclient import TestClient

    from app import setup_page
    from app.main import app

    monkeypatch.setattr(setup_page, "_local", lambda request: local)
    return TestClient(app)


def test_setup_page_saves_env_applies_settings_and_starts_the_crawl(setup_env, monkeypatch):
    from app import setup_page

    tmp, started = setup_env
    c = _client(monkeypatch, local=True)
    assert "Set up Robin" in c.get("/setup").text

    r = c.post("/setup", data={"site": "www.example-shop.test/", "host_full_name": "Asha Rao", "host_name_short": "Asha",
                               "host_email": "asha@example-shop.test", "booking": "", "provider": "groq",
                               "api_key": "gsk_test"}, follow_redirects=False)

    assert r.status_code == 303 and r.headers["location"] == "/setup/progress"
    env = (tmp / ".env").read_text(encoding="utf-8")
    assert "# keep me" in env and "SITE_BASE_URL=https://www.example-shop.test\n" in env
    assert "LLM_API_KEY=gsk_test\n" in env and "LLM_BASE_URL=https://api.groq.com/openai/v1\n" in env
    assert "ALLOWED_ORIGINS=https://example-shop.test,https://www.example-shop.test,http://localhost:8080\n" in env
    assert settings.site_base_url == "https://www.example-shop.test" and settings.host_email == "asha@example-shop.test"
    assert settings.llm_api_key == "gsk_test" and settings.chat_model == "openai/gpt-oss-120b"
    assert not setup_page.needs_setup() and started == [True]
    assert c.get("/setup", follow_redirects=False).status_code == 303  # configured: the form is gone
    assert c.get("/setup/status").json()["configured"] is True


def test_setup_page_keeps_a_shipped_central_key_when_none_is_pasted(setup_env, monkeypatch):
    tmp, started = setup_env
    (tmp / ".env").write_text("LLM_API_KEY=central-key\nLLM_BASE_URL=https://openrouter.ai/api/v1\n", encoding="utf-8")
    monkeypatch.setattr(settings, "llm_api_key", "central-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://openrouter.ai/api/v1")
    c = _client(monkeypatch, local=True)
    page = c.get("/setup").text
    assert "AI answers are included" in page and 'name="provider"' in page and "<select" not in page

    r = c.post("/setup", data={"site": "https://www.example-shop.test", "host_full_name": "Asha Rao",
                               "host_name_short": "Asha", "host_email": "asha@example-shop.test",
                               "provider": "openrouter", "api_key": ""}, follow_redirects=False)

    assert r.status_code == 303
    env = (tmp / ".env").read_text(encoding="utf-8")
    assert "LLM_API_KEY=central-key\n" in env and settings.llm_api_key == "central-key"
    assert "SITE_BASE_URL=https://www.example-shop.test\n" in env and started == [True]


def test_setup_page_refuses_remote_clients_and_bad_addresses(setup_env, monkeypatch):
    tmp, started = setup_env
    assert _client(monkeypatch, local=False).get("/setup").status_code == 403
    r = _client(monkeypatch, local=True).post("/setup", data={"site": "not a site", "host_full_name": "A",
                                                             "host_name_short": "A", "host_email": "a@b.test"},
                                              follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]
    assert started == [] and "SITE_BASE_URL=https://deependhq.com" in (tmp / ".env").read_text(encoding="utf-8")


def test_origin_check_without_origin_header_accepts_only_local_databases(monkeypatch):
    from app.main import _origin_ok

    req = types.SimpleNamespace(headers={})
    monkeypatch.delenv("ROBIN_EMBEDDED_DB", raising=False)
    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@prod.internal:5432/assistant")
    assert _origin_ok(req) is False                       # a deployed install still needs an Origin
    monkeypatch.setattr(settings, "database_url", "postgresql://postgres:@/postgres?host=/tmp/pg")
    assert _origin_ok(req) is True                        # pgserver on Linux: unix socket
    monkeypatch.setattr(settings, "database_url", "postgresql://u:p@prod.internal:5432/assistant")
    monkeypatch.setenv("ROBIN_EMBEDDED_DB", "1")
    assert _origin_ok(req) is True                        # the launcher marked the install as local


# ---------------------------------------------------------------- embeddings: remote option, no local model

def test_api_embeddings_use_the_remote_endpoint_and_check_the_size(monkeypatch):
    from app import embeddings

    class Data:
        def __init__(self, i, dim):
            self.index, self.embedding = i, [0.5] * dim

    class FakeClient:
        def __init__(self):
            self.calls = []
            self.embeddings = types.SimpleNamespace(create=self._create)

        def _create(self, model, input):
            self.calls.append((model, list(input)))
            return types.SimpleNamespace(data=[Data(i, embeddings.EMBED_DIM) for i in range(len(input))])

    fake = FakeClient()
    monkeypatch.setattr(settings, "embed_provider", "api")
    monkeypatch.setattr(settings, "embed_model", "text-embedding-3-small")
    monkeypatch.setattr(embeddings, "_client", fake)
    monkeypatch.setattr(embeddings, "_get_model", lambda: (_ for _ in ()).throw(AssertionError("local model must not load")))

    vecs = embeddings.embed_texts(["a", "b"])
    q = embeddings.embed_query("hello")

    assert len(vecs) == 2 and len(vecs[0]) == embeddings.EMBED_DIM and len(q) == embeddings.EMBED_DIM
    assert fake.calls[0] == ("text-embedding-3-small", ["a", "b"]) and fake.calls[1][1] == ["hello"]


def test_api_embeddings_without_a_key_fail_loudly(monkeypatch):
    from app import embeddings

    monkeypatch.setattr(settings, "embed_provider", "api")
    monkeypatch.setattr(settings, "embed_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(embeddings, "_client", None)

    with pytest.raises(RuntimeError, match="EMBED_API_KEY"):
        embeddings.embed_query("hello")
