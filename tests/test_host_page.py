"""The host's private booking page (app/host_page.py): the signed link bound to one booking row, what the page shows and
never shows, escaping, the states, the emails that link it, and (against Postgres) the route: private headers, bad
tokens, and nothing written on GET."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import host_page, links, outcomes, precall, templates
from app.config import settings
from tests.test_precall import NOW, M, sig
from tests.test_reminders import _db_up

TEST_IP = "203.0.113.7"   # TEST-NET-3: never a real visitor's address


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "link_secret", "s")
    monkeypatch.setattr(settings, "public_base_url", "https://assistant.example.com")
    monkeypatch.setattr(settings, "tracking_enabled", True)


def _token(url: str) -> str:
    return re.search(r"[?&]t=([^&]+)", url).group(1)


def page(b_over: dict | None = None, **over) -> str:
    """The sample page's inputs (Ada, ended, a v2 brief) with overrides, through the real assemble() and render()."""
    p = host_page.sample_inputs()
    p["b"] = dict(p["b"], **(b_over or {}))
    p.update(over)
    return host_page.render(host_page.assemble(p.pop("b"), **p))


# ---------------------------------------------------------------- the signed link
def test_link_is_bound_to_kind_and_row(monkeypatch):
    b = {"id": 42, "manage_token": "Tok"}
    u = host_page.link(b)
    assert u.startswith("https://assistant.example.com/host/booking/42?t=")
    t = _token(u)
    assert host_page.check(b, t)
    assert not host_page.check({"id": 43, "manage_token": "Tok"}, t)
    assert not host_page.check({"id": 42, "manage_token": "Other"}, t)        # a rebuilt DB reusing id 42 does not open
    assert not links.check("outcome", 42, t) and not host_page.check(b, links.sign("outcome", 42))
    assert not host_page.check(b, "é") and not host_page.check(b, None) and not host_page.check({"id": 42}, "")
    assert host_page.link({"id": 42}) == ""                                    # no manage token, no link
    hb = host_page.attach(b)
    assert hb is not b and hb["host_url"] == u and "host_url" not in b
    assert host_page.attach({"id": 42}) == {"id": 42}
    for k in ("link_secret", "admin_token", "widget_signing_secret"):
        monkeypatch.setattr(settings, k, "")
    assert host_page.link(b) == ""


# ---------------------------------------------------------------- what the page shows
def test_render_shows_what_the_host_needs():
    from app.booking.flow import _booking_view

    p = host_page.sample_inputs()
    secret = {"manage_token": "MANAGE-SECRET-TOKEN", "handoff_url": "https://scheduler.zoom.us/x?handoff=visitor",
              "zoom_cancel_url": "https://scheduler.zoom.us/cancel/ZC1", "zoom_reschedule_url": "https://scheduler.zoom.us/resched/ZR1",
              "manage_url": "https://assistant.example.com/booking/42/manage?t=MANAGE-SECRET-TOKEN"}
    net = dict(p["sig"]["network"], ip=TEST_IP)
    earlier = [dict(p["earlier"][0], ip=TEST_IP, user_agent="Mozilla/5.0 SECRET-UA", lat=12.9, lon=77.6)]
    h = page(secret, sig=dict(p["sig"], network=net, ip=TEST_IP), earlier=earlier)
    v = _booking_view(p["b"])
    for s in ("Ada Lovelace", v["label_host"], "Their time:", "Confirmed", "Join Zoom", "href='https://zoom.us/j/81234567890?pwd=sample'",
              "[file: brief.pdf]", "Already has another upcoming call booked", "Fit", "Risk", "+15 company email", "Written by the model",
              "/admin#booking=42", "same browser", "Lovelace Analytical Engines", "(from their website)", "Charles Babbage"):
        assert s in h, s
    for s in ("Cancel this booking", "MANAGE-SECRET-TOKEN", "/booking/42/manage", "/uploads/", "handoff=visitor", "ZC1", "ZR1", TEST_IP,
              "SECRET-UA", "12.9", "<script"):
        assert s not in h, s
    assert h.count("/outcome/42?t=") == 4                                  # the call ended: the four rating buttons
    s = host_page.render(host_page.sample())
    assert s.count("/outcome/") == 0 and s.count("href='#'") == 4          # the sample's rating buttons go nowhere


def test_render_escapes_and_never_links_free_text():
    p = host_page.sample_inputs()
    rows = p["transcript"] + [{"ts": NOW, "role": "assistant", "text": "Read https://evil.example/a now", "outcome": "answered"}]
    brief = dict(p["brief"], summary="Click https://evil.example/phish <b>now</b>")
    h = page({"name": "<script>x</script>", "join_url": "javascript:alert(1)", "email": "a@b.com?bcc=x@y.z",
              "notes": "visit https://evil.example/n"}, transcript=rows, brief=brief)
    assert "<script>x" not in h and "&lt;script&gt;x&lt;/script&gt;" in h
    assert "javascript:" not in h and "Join Zoom" not in h
    assert "https://evil.example/a" in h and "https://evil.example/phish" in h and "&lt;b&gt;now" in h
    assert "href='https://evil" not in h and 'href="https://evil' not in h
    assert "mailto:a@b.com" not in h and "Email Ada" not in h


def test_render_states_brief_variants_outcome_and_earlier_visits():
    p = host_page.sample_inputs()
    h = page({"status": "pending_zoom", "method": "handoff"})
    assert "Awaiting Zoom confirmation" in h and "Join Zoom" not in h and "still has to confirm on Zoom" in h
    h = page({"method": "browser", "join_url": None})
    assert "Zoom Scheduler put on your calendar" in h and "Join Zoom" not in h
    h = page({"status": "cancelled", "cancelled_at": NOW})
    assert "Cancelled" in h and "/outcome/" not in h and "Call outcome" not in h and "Join Zoom" not in h
    h = page({"rescheduled_at": NOW, "previous_start_utc": datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)})
    assert "Moved" in h and "Was: Tue 06 Oct" in h
    h = page({"zoom_error": "Scheduler said no " + "x" * 400})
    assert "Zoom said: Scheduler said no" in h and "x" * 300 not in h

    v1 = {k: v for k, v in p["brief"].items() if k not in ("groups", "flags", "at_booking")}
    h = page(brief=dict(v1, version=1, composer="rules"))
    assert "class='tiles'" not in h and "old score, refresh in console" in h and "Rule-based brief" in h
    live = precall.score(sig(), adjust={})
    h = page(brief=live, brief_live=True)
    assert "live rules score" in h and "Live rules score: no brief was stored" in h and "class='tiles'" in h
    assert "Already has another" not in page(brief=dict(p["brief"], flags=[], watch_outs=[]))   # no WATCH OUT box when empty

    d = host_page.assemble(**{**{k: v for k, v in p.items() if k != "b"}, "b": p["b"]})
    assert len(d["outcome"]["links"]) == 4
    assert host_page.render(d).count("/outcome/42?t=") == 4                 # ended: the four rating buttons
    future = dict(p, now=p["b"]["start_utc"] - timedelta(days=1))
    d = host_page.assemble(future.pop("b"), **future)
    assert d["outcome"] is None and "/outcome/" not in host_page.render(d) and "starts in 24 h" in host_page.render(d)
    rated = host_page.render(host_page.assemble(dict(p["b"], outcome="good_fit", outcome_note="wants 500 rows",
                                                     followup={"sent_at": "2026-10-08T10:00:00+00:00"}),
                                                **{k: v for k, v in p.items() if k != "b"}))
    assert "Good fit" in rated and "wants 500 rows" in rated and "Follow-up sent" in rated and "Change the outcome" in rated

    e = [dict(p["earlier"][0], page="https://deependhq.com/pricing?email=a@b.com", first_q=None, via="email")]
    h = page(earlier=e)
    assert "/pricing" in h and "email=" not in h and "same email (unverified)" in h
    h = page(transcript=[], total=0)
    assert "Booked from the form; no chat messages." in h
    long = [{"ts": NOW, "role": "assistant", "text": "A" * 900, "outcome": "answered"},
            {"ts": NOW, "role": "assistant", "text": "Booking confirmed: call", "outcome": "booking"}]
    h = page(transcript=long, total=250)
    assert "<details><summary>" in h and "class='sys'" in h and "Showing the first 2 of 250" in h


def test_company_view_agrees_with_facts_text():
    cases = [
        (sig(company_verified=True), "website", "Company (from their website)"),
        (sig(company_verified=False), "domain", "Company (from the email domain"),
        (sig(email="x@gmail.com", domain="gmail.com", email_kind="personal", company_line="", company_typed="Apple.INC"),
         "typed_personal", "Company they typed (unverified, personal email)"),
        (sig(company_typed="Hopper Systems"), "typed", "Company they typed (unverified)"),
    ]
    for s, trust, prefix in cases:
        v = precall.company_view(s)
        assert v["trust"] == trust and prefix in precall.facts_text(s, precall.score(s, adjust={})), trust
    assert precall.company_view(sig(company_verified=True))["name"] == "Lovelace Analytical Engines"
    assert precall.company_view(sig(company_typed="Hopper Systems"))["also"] == "Lovelace Analytical Engines"
    assert precall.company_view({})["trust"] == ""


# ---------------------------------------------------------------- the emails that link it
def _booking(**over):
    b = dict(templates.SAMPLE_BOOKING, manage_token="Tok", session_id=None, outcome=None, outcome_note=None, followup=None,
             start_utc=datetime.now(timezone.utc) + timedelta(hours=22))
    b.update(over)
    return b


def test_day_before_and_brief_now_link_the_host_page(monkeypatch):
    brief = precall.build(sig(), ask=lambda s, f: json.dumps({"summary": "Ada wants EU fintech data.", "talking_points": ["Show coverage"]}))
    monkeypatch.setattr(precall, "build_for_booking", lambda booking, refresh=False, ask=None, save=True, **k: brief)
    for send in (lambda b, m: precall.send_host_reminder(b, mailer=m, ask=lambda s, f: ""), lambda b, m: precall.send_brief_now(b, mailer=m)):
        m = M()
        send(_booking(), m)
        to, subject, body, kw = m.items[0]
        assert "/host/booking/42?t=" in kw["html"] and "Open booking page" in kw["html"] and "Booking page: https://" in body
        m = M()
        send(_booking(manage_token=None), m)
        assert "Open booking page" not in m.items[0][3]["html"] and "Booking page:" not in m.items[0][2]
    subject, text, base, buttons = outcomes.render_ask(_booking())
    assert "Booking page: https://assistant.example.com/host/booking/42?t=" in text
    html = templates.html_wrap(subject, base, audience="host", actions=buttons)
    assert html.count('href="https://assistant.example.com/outcome/42') == 4 and "/host/booking/42?t=" in html


def test_outcome_pages_link_the_host_page():
    b = _booking()
    assert "Open the full booking page" in outcomes.page_ask(b, "tok") and "/host/booking/42?t=" in outcomes.page_ask(b, "tok")
    assert "Open the full booking page" in outcomes.page_saved(dict(b, outcome="not_fit"), "tok", None)
    assert "Open the full booking page" not in outcomes.page_ask(_booking(manage_token=None), "tok")


def test_preview_and_send_test_use_the_sample_page(monkeypatch):
    from fastapi.testclient import TestClient

    from app import db
    from app.booking import email as mail
    from app.main import app

    assert "Booking page: https://assistant.deependhq.com/host/booking/sample" in templates.preview("host_booking")["body"]
    seen = {}
    monkeypatch.setattr(mail, "_send", lambda to, subject, body, reply_to=None, html=None, attachments=None: seen.update(body=body, html=html) or True)
    assert mail.send_test("host_booking")["ok"]
    assert links.base_url() + "/host/booking/sample" in seen["html"] and "/manage" not in seen["html"]
    assert "Booking page: " + links.base_url() + "/host/booking/sample" in seen["body"]

    def no_db():
        raise AssertionError("the sample page touched the database")

    monkeypatch.setattr(db, "conn", no_db)
    r = TestClient(app).get("/host/booking/sample")
    assert r.status_code == 200 and "Ada Lovelace" in r.text and "default-src 'none'" in r.headers["content-security-policy"]
    assert "no-store" in r.headers["cache-control"] and "<script" not in r.text


# ---------------------------------------------------------------- the route, against Postgres
def _snapshot(bid: int, sids: list[str]) -> dict:
    from app.db import conn

    with conn() as c:
        return {"booking": c.execute("SELECT brief_at, origin, brief, manage_token FROM bookings WHERE id = %s", (bid,)).fetchone(),
                "messages": c.execute("SELECT count(*) FROM messages WHERE session_id = ANY(%s)", (sids,)).fetchone()[0],
                "events": c.execute("SELECT count(*) FROM events WHERE session_id = ANY(%s)", (sids,)).fetchone()[0],
                "sessions": c.execute("SELECT * FROM sessions WHERE session_id = ANY(%s) ORDER BY session_id", (sids,)).fetchall(),
                "memory": c.execute("SELECT count(*) FROM session_memory WHERE session_id = ANY(%s)", (sids,)).fetchone()[0]}


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_host_page_route_is_read_only_and_private(monkeypatch):
    from fastapi.testclient import TestClient

    from app import store_bookings
    from app.db import conn
    from app.main import app

    client = TestClient(app)
    sid, sid2, vid = f"test-{uuid.uuid4()}", f"test-{uuid.uuid4()}", f"test-vis-{uuid.uuid4()}"
    start = datetime(2020, 1, 6, 10, 0, tzinfo=timezone.utc)
    bid = None
    try:
        with conn() as c:
            c.execute("""INSERT INTO sessions(session_id, visitor_id, ip, geo_status, city, country_code, net_kind, net_org, messages, channel,
                                              first_seen, last_seen)
                         VALUES (%s, %s, %s, 'ok', 'Bengaluru', 'IN', 'consumer', 'ACT', 3, 'direct', %s, %s)""",
                      (sid, vid, TEST_IP, start - timedelta(hours=1), start - timedelta(minutes=50)))
            c.execute("""INSERT INTO sessions(session_id, visitor_id, ip, geo_status, messages, channel, page, first_seen, last_seen)
                         VALUES (%s, %s, %s, 'ok', 2, 'search', 'https://deependhq.com/pricing?email=a@b.com', %s, %s)""",
                      (sid2, vid, TEST_IP, start - timedelta(days=3), start - timedelta(days=3)))
            for role, text, outcome in (("user", "[attached: deck.pdf](/uploads/abc) here is our deck", None),
                                        ("user", "<img src=x onerror=alert(1)>", None),
                                        ("assistant", "Booking confirmed: Discovery Call.", "booking")):
                c.execute("INSERT INTO messages(session_id, role, text, outcome) VALUES (%s, %s, %s, %s)", (sid, role, text, outcome))
            c.commit()
        bid = store_bookings.insert({"session_id": sid, "name": "Ada Test", "email": f"{sid}@example.test", "schedule_slug": "discovery-call",
                                     "schedule_name": "Discovery Call", "duration_min": 30, "start_utc": start, "end_utc": start + timedelta(minutes=30),
                                     "visitor_tz": "Asia/Kolkata", "method": "handoff", "status": "confirmed", "manage_token": "t" + sid,
                                     "origin": "Bengaluru, IN · direct"})
        precall.store(bid, {"version": 2, "score": 66, "label": "hot", "composer": "model", "summary": "SUMMARY-X",
                            "built_at": "2026-10-06T08:00:00+00:00", "groups": {"fit": 15, "intent": 20, "engagement": 21, "risk": 0},
                            "flags": [{"key": "open_booking", "text": "FLAG-Y"}],
                            "reasons": [{"key": "business_email", "points": 15, "text": "company email", "group": "fit"}],
                            "at_booking": {"version": 2, "score": 60, "label": "hot"}})
        b = store_bookings.get(bid)
        url = host_page.link(b)

        monkeypatch.setattr(settings, "admin_token", "x")        # the stored brief comes back: no rebuild, no model call
        before = _snapshot(bid, [sid, sid2])
        r = client.get(f"/admin/bookings/{bid}/brief", headers={"X-Admin-Token": "x"})
        assert r.status_code == 200 and r.json()["host_url"] == url and r.json()["brief"]["summary"] == "SUMMARY-X"
        assert _snapshot(bid, [sid, sid2]) == before

        r = client.get(f"/host/booking/{bid}", params={"t": _token(url)})
        assert r.status_code == 200
        hd = r.headers
        assert "no-store" in hd["cache-control"] and hd["referrer-policy"] == "no-referrer" and "noindex" in hd["x-robots-tag"]
        assert hd["x-frame-options"] == "DENY" and "default-src 'none'" in hd["content-security-policy"]
        t = r.text
        for s in ("[file: deck.pdf]", "&lt;img", "SUMMARY-X", "FLAG-Y", "same browser", "Ada Test", "/pricing", "home broadband"):
            assert s in t, s
        assert t.count(f"/outcome/{bid}?t=") == 4
        for s in (TEST_IP, "t" + sid, "/uploads/abc", "email=a@b.com", "<script"):
            assert s not in t, s
        assert _snapshot(bid, [sid, sid2]) == before                 # GET wrote nothing

        for bad in ("bad", "é", links.sign("outcome", bid), "x" * 500, ""):
            assert client.get(f"/host/booking/{bid}", params={"t": bad}).status_code == 404, bad
        with conn() as c:                                            # rotating the row's manage token revokes the link
            c.execute("UPDATE bookings SET manage_token = %s WHERE id = %s", ("u" + sid, bid))
            c.commit()
        assert client.get(f"/host/booking/{bid}", params={"t": _token(url)}).status_code == 404

        with conn() as c:                                            # nothing stored: a live rules score, still nothing written
            c.execute("UPDATE bookings SET brief = NULL, brief_at = NULL WHERE id = %s", (bid,))
            c.commit()
        b = store_bookings.get(bid)
        before = _snapshot(bid, [sid, sid2])
        r = client.get(f"/host/booking/{bid}", params={"t": _token(host_page.link(b))})
        assert r.status_code == 200 and "live rules score" in r.text and "SUMMARY-X" not in r.text
        assert _snapshot(bid, [sid, sid2]) == before
    finally:
        with conn() as c:
            if bid:
                c.execute("DELETE FROM bookings WHERE id = %s", (bid,))
            for t in ("messages", "events", "session_memory", "sessions"):
                c.execute(f"DELETE FROM {t} WHERE session_id = ANY(%s)", ([sid, sid2],))
            c.commit()


# ---------------------------------------------------------------- evidence: checked, seen, their word
def test_page_shows_evidence_tags_verdict_and_claims():
    h = page()
    assert "+15 company email (lovelace.org)<span class='ev verified'>checked: website</span>" in h
    assert "+25 asked about pricing, a trial or sample data<span class='ev observed'>seen</span>" in h
    assert "Evidence: 20 pts checked · 37 pts seen · 1 claim not scored" in h
    assert "<h3>What they say (not scored)</h3><ul><li>they say: role: head of data partnerships</li></ul>" in h
    assert "Why this score</h3><ul>" in h and "they say: role" not in h.split("Why this score", 1)[1].split("</ul>", 1)[0]
    assert ">Hot lead · 72/100<" in h and "old score" not in h
    # a live v3 score of a thin booking: the verdict, and a spoofed tag in their words stays plain text
    p = host_page.sample_inputs()
    thin = precall.score(sig(email="r@gmail.com", domain="gmail.com", email_kind="personal", company_line="", company_typed="Apple.INC",
                             questions=[], question_count=0, visits=1, notes="", told={"role": "CEO [checked: website]"},
                             start_utc=NOW + timedelta(days=9)), adjust={})
    h = page(brief=thin, brief_live=True)
    assert "Not enough data yet · " in h and "/100 · Not enough data yet<" in h
    assert "<li>they say: role: CEO [checked: website]</li>" in h and "says they are from Apple.INC (unverified, personal email)</li>" in h
    assert "personal email but says they are from Apple.INC<span class='ev risk'>warning</span>" in h
    # a v2 brief: no tags, its own label, marked old
    v2 = dict(p["brief"], version=2, verdict=None, evidence=None, reasons=[{"key": "visits", "points": 8, "text": "came back"}])
    h = page(brief=v2)
    assert "+8 came back</li>" in h and "class='ev" not in h and "Hot lead · 72/100" in h and "old score, refresh in console" in h
    # a dead email domain: no company confirmed
    dead = dict(p["sig"], domain_proof="dead", company_verified=False, enrich_source="")
    h = page(sig=dead)
    assert "none confirmed" in h and "their email domain does not exist or takes no mail; they typed: Lovelace Analytical Engines" in h
    mx = dict(p["sig"], domain_proof="mx", company_verified=False, enrich_source="", company_typed="")
    assert "from their email domain, which receives mail; website not checked" in page(sig=mx)


# ---------------------------------------------------------------- review fixes
def test_shared_browser_earlier_visits_are_only_their_own():
    p = host_page.sample_inputs()
    own = p["earlier"][0]                                                      # their own visit on this browser (sample-0)
    other = dict(own, session_id="sample-x", first_q="Do you sell hospital contacts?", net_org="Babbage Engines")
    by_email = dict(own, session_id="sample-e", first_q="Is there an API?", via="email")
    rows = [own, other, by_email]
    h = page(earlier=rows)                                                     # nobody else on the browser: every visit shows
    assert "Do you sell hospital contacts?" in h and "Shared browser" not in h
    shared = dict(p["sig"], shared_browser=1, session_ids=["sample", "sample-0"])
    h = page(earlier=rows, sig=shared)
    assert "Do you sell hospital contacts?" not in h and "Babbage Engines" not in h
    assert "How do you price contact data?" in h and "Is there an API?" in h
    assert "Shared browser: other people's visits on it are hidden." in h
    assert [r["session_id"] for r in host_page.own_earlier(rows, shared)] == ["sample-0", "sample-e"]


def test_a_zero_score_shows_as_zero():
    p = host_page.sample_inputs()
    h = page(brief=dict(p["brief"], score=0, at_booking={"score": 12}))
    assert "<div class='score'><b>0</b><span>/100" in h and "At booking: 12</span>" in h
    h = page(brief=dict(p["brief"], score=7, at_booking={"score": 0}))
    assert "<b>7</b>" in h and "<span class='note'>At booking: 0</span>" in h
