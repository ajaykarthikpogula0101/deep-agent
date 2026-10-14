"""Call outcomes (app/outcomes.py): the signed links, the "how did it go?" email, the follow-up draft and its fallback,
the score learning from outcomes, and (against Postgres) the whole loop: ask once, the page behind the buttons, saving,
drafting, sending."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import links, outcomes, precall, templates
from app.config import settings
from tests.test_precall import NOW, M, sig
from tests.test_reminders import _db_up


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(settings, "link_secret", "test-link-secret")
    monkeypatch.setattr(settings, "public_base_url", "https://assistant.example.com")


def booking(**over):
    b = dict(templates.SAMPLE_BOOKING, id=42, session_id=None, outcome=None, outcome_note=None, followup=None)
    b.update(over)
    return b


def test_links_are_signed_per_kind_and_value(monkeypatch):
    t = links.sign("outcome", 42)
    assert t and links.check("outcome", 42, t) and links.check("outcome", "42", t)
    assert not links.check("outcome", 43, t) and not links.check("optout", 42, t) and not links.check("outcome", 42, t[:-1] + "x")
    assert links.check("optout", "Ada@Lovelace.org", links.sign("optout", "ada@lovelace.org"))   # emails compare case-insensitively
    for k in ("link_secret", "admin_token", "widget_signing_secret"):
        monkeypatch.setattr(settings, k, "")
    assert not links.enabled() and links.sign("outcome", 42) == "" and not links.check("outcome", 42, "")


def test_ask_email_has_four_signed_buttons_and_the_lead_score():
    brief = {"score": 72, "label": "hot"}
    subject, text, base, buttons = outcomes.render_ask(booking(), brief)
    assert subject == "[LakeB2B] How did the call with Ada Lovelace go? · LakeB2B Discovery Call · " + subject.rsplit(" · ", 1)[1]
    assert [b[0] for b in buttons] == ["Good fit", "Follow up", "Not a fit", "No-show"]
    for (label, url), key in zip(buttons, outcomes.OUTCOMES):
        assert url.startswith("https://assistant.example.com/outcome/42?t=") and url.endswith("&o=" + key)
        assert links.check("outcome", 42, re.search(r"t=([^&]+)", url).group(1))
        assert f"{label}: {url}" in text and url not in base
    assert "Lead:     Hot lead · 72/100 (at booking)" in base
    html = templates.html_wrap(subject, base, audience="host", actions=buttons)
    assert html.count('href="https://assistant.example.com/outcome/42') == 4 and "Good fit</a>" in html and "No-show</a>" in html


def test_follow_up_draft_from_the_model_and_its_fallbacks(monkeypatch):
    seen = {}

    def ask(system, facts):
        seen["system"], seen["facts"] = system, facts
        return json.dumps({"subject": "Great talking today, Ada", "body": "Hi Ada,\n\nThanks for the call. As promised, the 500-contact EU fintech sample "
                                                                        "follows by Friday.\n\nBest,\nDeep"})

    monkeypatch.setattr(precall, "gather", lambda *a, **k: sig())
    d = outcomes.draft_followup(booking(outcome="good_fit", outcome_note="send 500 EU fintech sample by Friday"), ask=ask, save=False)
    assert d["subject"] == "Great talking today, Ada" and d["composer"] == "model" and d["mode"] == "good_fit"
    assert "send 500 EU fintech sample by Friday" in seen["facts"] and "Call outcome: Good fit" in seen["facts"]
    assert "never guess gender" in seen["system"] and "sign off with 'Deep'" in seen["system"]
    assert outcomes.draft_followup(booking(outcome="not_fit"), ask=ask, save=False) is None
    assert outcomes.draft_followup(booking(outcome=None), ask=ask, save=False) is None
    # the model fails or answers nonsense: the rules write it, a no-show gets the booking link
    ns = outcomes.draft_followup(booking(outcome="no_show"), ask=lambda s, f: (_ for _ in ()).throw(TimeoutError("slow")), save=False)
    assert ns["composer"] == "rules" and ns["model_error"] == "slow" and settings.zoom_booking_base in ns["body"] and ns["subject"] == "Sorry we missed you, Ada"
    fu = outcomes.draft_followup(booking(outcome="follow_up", outcome_note="Pricing for 3 regions"), ask=lambda s, f: "not json", save=False)
    assert fu["composer"] == "rules" and "As discussed: Pricing for 3 regions" in fu["body"] and fu["body"].rstrip().endswith("Deep")
    assert outcomes.parse_email('{"subject": "Hi", "body": "too short"}') is None


def test_score_learns_from_outcomes_and_explains_the_change(monkeypatch):
    # 24 rated calls: company emails mostly good, people asking about jobs never, the rest mixed
    samples = ([({"business_email": 15, "questions": 10}, True)] * 9 + [({"business_email": 15}, False)] * 2
               + [({"personal_email": 0, "jobs": -25}, False)] * 5 + [({"personal_email": 0, "questions": 4}, True)] * 3
               + [({"personal_email": 0}, False)] * 5)
    L = outcomes.calibrate(samples, min_calls=20)
    assert L["calls"] == 24 and L["good"] == 12 and L["good_rate"] == 0.5 and L["active"]
    adj = L["adjust"]
    assert adj["business_email"] > 0 and adj["questions"] > 0 and adj["jobs"] < 0 and adj["personal_email"] < 0
    assert all(abs(v) <= outcomes.LEARN_CAP for v in adj.values())
    row = next(r for r in L["table"] if r["key"] == "business_email")
    assert row == {"key": "business_email", "rule": "company email", "calls": 11, "good": 9, "good_rate": 0.82, "adjust": adj["business_email"]}
    s = L["separation"]
    assert s["good_after"] - s["rest_after"] > s["good_before"] - s["rest_before"]   # the learned weights separate better
    # below the minimum it only shows what it would learn; one rule seen twice never moves
    few = outcomes.calibrate(samples[:12], min_calls=20)
    assert not few["active"] and few["adjust"] == {} and few["would_adjust"]
    assert outcomes.calibrate([({"vendor": -15}, False)] * 2 + [({"x": 1}, True)] * 20, min_calls=20)["adjust"].get("vendor", 0) == 0
    monkeypatch.setattr(settings, "score_learning", False)
    assert not outcomes.calibrate(samples, min_calls=20)["active"]


def test_score_applies_learned_points_and_keeps_the_original():
    base = precall.score(sig(), adjust={})
    learned = precall.score(sig(), adjust={"business_email": 6, "visits": -4})
    r = {x["key"]: x for x in learned["reasons"]}
    assert r["business_email"]["points"] == 21 and r["business_email"]["base"] == 15 and r["visits"]["points"] == 4
    assert "base" not in r["questions"] and learned["score"] == base["score"] + 2 and learned["learned"] and not base["learned"]
    assert all("key" in x for x in base["reasons"]) and set(r) <= set(precall.RULES)


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_whole_loop_ask_once_rate_on_the_page_draft_and_send(monkeypatch):
    from fastapi.testclient import TestClient

    from app import mailer, store_bookings as sb
    from app.db import conn
    from app.main import app

    tag = uuid.uuid4().hex[:8]
    email = f"ada.{tag}@lovelace-engines.com"
    end = datetime.now(timezone.utc) - timedelta(minutes=45)
    bid = sb.insert({"session_id": None, "name": "Ada Lovelace", "email": email, "schedule_slug": "discovery-call", "schedule_name": "LakeB2B Discovery Call",
                     "duration_min": 15, "start_utc": end - timedelta(minutes=15), "end_utc": end, "visitor_tz": "Europe/London",
                     "method": "browser", "status": "confirmed", "manage_token": "t" + tag})
    sent = []
    monkeypatch.setattr(mailer.default, "enqueue", lambda to, subject, body, **kw: sent.append((to, subject, body, kw)))
    monkeypatch.setattr(outcomes, "_ask_model", lambda s, f: json.dumps({"subject": "Thanks, Ada", "body": "Hi Ada,\n\nThanks for the call today. The sample follows by Friday.\n\nBest,\nDeep"}))
    try:
        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        assert [b["id"] for b in outcomes.due(since_iso=since) if b["id"] == bid] == [bid]
        monkeypatch.setattr(outcomes, "due", lambda: [sb.get(bid)])   # never ask about real bookings in the database
        m = M()
        r = outcomes.send_asks(mailer=m)
        assert r["sent"] == 1 and m.items[0][0] == settings.host_email and "How did the call with Ada Lovelace go?" in m.items[0][1]
        assert sb.get(bid)["outcome_asked_at"] is not None
        client = TestClient(app)
        t = links.sign("outcome", bid)
        assert client.get(f"/outcome/{bid}?t=bad&o=good_fit").status_code == 404
        page = client.get(f"/outcome/{bid}?t={t}&o=good_fit")
        assert page.status_code == 200 and "value='good_fit' checked" in page.text and "How did the call with Ada Lovelace go?" in page.text
        saved = client.post(f"/outcome/{bid}?t={t}", data={"o": "good_fit", "note": "sample by Friday"})
        assert saved.status_code == 200 and "Your follow-up is drafted" in saved.text and "Thanks, Ada" in saved.text
        b = sb.get(bid)
        assert b["outcome"] == "good_fit" and b["outcome_note"] == "sample by Friday" and b["followup"]["composer"] == "model"
        done = client.post(f"/outcome/{bid}/send?t={t}", data={"subject": "Thanks, Ada", "body": "Hi Ada,\n\nEdited by Deep before sending. Best,\nDeep"})
        assert "on its way to " + email in done.text
        assert [x[0] for x in sent] == [email] and sent[0][3]["reply_to"] == settings.host_email and "Edited by Deep" in sent[0][2]
        again = client.post(f"/outcome/{bid}/send?t={t}", data={"subject": "x", "body": "y" * 30})
        assert "already sent" in again.text and len(sent) == 1
        assert sb.get(bid)["followup"]["sent_at"]
        week = outcomes.week(1)
        assert week["calls"] >= 1 and week["by_outcome"]["good_fit"] >= 1 and outcomes.week_line(week).startswith(f"{week['calls']} call")
    finally:
        with conn() as c:
            c.execute("DELETE FROM bookings WHERE id = %s", (bid,))
            c.execute("DELETE FROM events WHERE kind IN ('outcome_asked', 'call_outcome', 'call_followup_sent') AND detail->>'booking_id' = %s", (str(bid),))
            c.commit()
        outcomes.learn()   # the stored learning summary no longer counts this test's call
