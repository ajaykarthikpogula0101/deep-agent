"""Proactive outreach rules: matching, templating and validation hermetically; cooldown, attribution and CRUD with Postgres."""
from __future__ import annotations

import uuid

import pytest

from app import outreach as o


# ---------------------------------------------------------------- pure helpers
def test_path_of_and_patterns():
    assert o.path_of("https://deependhq.com/company/lake-b2b?utm_source=x") == "/company/lake-b2b"
    assert o.path_of("https://deependhq.com/journey.html#day-184") == "/journey.html#day-184"
    assert o.path_of("/pillars?x=1#top") == "/pillars#top"
    assert o.path_of("") == "/"
    assert o.path_matches("", "/anything")
    assert o.path_matches("/company/lake-b2b", "/company/lake-b2b")
    assert o.path_matches("/company/", "/company/ampliz")              # starts-with
    assert o.path_matches("/journey", "/journey.html#day-200")
    assert o.path_matches("/company/*", "/company/lake-b2b") and not o.path_matches("/company/*", "/journey")
    assert o.path_matches("/pricing|/plans", "/plans") and not o.path_matches("/pricing|/plans", "/about")
    assert o.path_matches("/", "/") and not o.path_matches("/", "/company/x")   # "/" means the home page only
    assert o.path_matches("/COMPANY/", "/company/x")                              # case-insensitive


def _ctx(**kw):
    base = {"path": "/", "pages": ["/"], "dwell_s": 0, "scroll_pct": 0, "referrer_host": "", "channel": "direct", "utm_source": "",
            "visits": 1, "returning": False, "booking": False, "booking_label": None, "schedule": None, "first_name": "", "topic": None,
            "page_title": ""}
    base.update(kw)
    return base


def test_evaluate_fixed_conditions_and_waits():
    t = {"page": "/company/lake-b2b", "dwell_s": 45, "booking": "no"}
    assert o.evaluate(t, _ctx(path="/journey"))["match"] is False and "wait" not in o.evaluate(t, _ctx(path="/journey"))
    r = o.evaluate(t, _ctx(path="/company/lake-b2b", dwell_s=10))
    assert r == {"match": False, "wait": {"dwell_s": 45}}                     # right page, not long enough yet
    assert o.evaluate(t, _ctx(path="/company/lake-b2b", dwell_s=45))["match"] is True
    assert o.evaluate(t, _ctx(path="/company/lake-b2b", dwell_s=90, booking=True))["match"] is False
    t2 = {"pages_min": 3, "pages_match": "/company/"}
    assert o.evaluate(t2, _ctx(pages=["/", "/company/a", "/company/b"]))["match"] is False
    assert o.evaluate(t2, _ctx(pages=["/company/a", "/company/b", "/company/B", "/company/c"]))["match"] is True  # distinct, case-insensitive
    t3 = {"page": "/journey", "scroll_pct": 85, "dwell_s": 60}
    assert o.evaluate(t3, _ctx(path="/journey", dwell_s=10, scroll_pct=20)) == {"match": False, "wait": {"dwell_s": 60, "scroll_pct": 85}}
    assert o.evaluate(t3, _ctx(path="/journey", dwell_s=61, scroll_pct=90))["match"] is True
    assert o.evaluate({"visitor": "returning"}, _ctx())["match"] is False
    assert o.evaluate({"visitor": "returning"}, _ctx(returning=True))["match"] is True
    assert o.evaluate({"visitor": "new"}, _ctx(returning=True))["match"] is False
    assert o.evaluate({"booking": "yes"}, _ctx(booking=True))["match"] is True
    assert o.evaluate({"referrer": "linkedin"}, _ctx(referrer_host="www.linkedin.com"))["match"] is True
    assert o.evaluate({"referrer": "linkedin"}, _ctx(referrer_host="google.com"))["match"] is False
    assert o.evaluate({"channel": "search,social"}, _ctx(channel="social"))["match"] is True
    assert o.evaluate({"channel": "search"}, _ctx(channel="direct"))["match"] is False
    assert o.evaluate({"utm_source": "newsletter"}, _ctx(utm_source="Newsletter"))["match"] is True
    assert o.evaluate({}, _ctx())["match"] is True                               # an empty trigger matches everyone


def test_context_derives_channel_referrer_and_facts():
    payload = {"page": "https://deependhq.com/company/ampliz?utm_source=li&utm_medium=cpc", "path": "/company/ampliz",
               "pages": ["https://deependhq.com/", "/company/lake-b2b"], "dwell_s": 12, "scroll_pct": 40,
               "referrer": "https://www.linkedin.com/feed/", "first_page": "https://deependhq.com/?utm_source=li&utm_medium=cpc", "visits": 3}
    facts = {"returning": True, "visits": 2, "name": "Ada Lovelace", "topics": ["LakeB2B pricing"],
             "upcoming": {"schedule_name": "Discovery Call", "label_visitor": "Thu 15 Oct, 16:30"}}
    c = o.context(payload, facts)
    assert c["path"] == "/company/ampliz" and c["pages"] == ["/", "/company/lake-b2b", "/company/ampliz"]
    assert c["referrer_host"] == "linkedin.com" and c["channel"] == "paid" and c["utm_source"] == "li"
    assert c["returning"] and c["visits"] == 3 and c["booking"] and c["booking_label"] == "Thu 15 Oct, 16:30"
    assert c["first_name"] == "Ada" and c["topic"] == "LakeB2B pricing" and c["schedule"] == "Discovery Call"
    assert o.context({"visits": 2}, {})["returning"] is True      # two visits counted on the device count as returning
    assert o.context({"visits": 1}, {})["returning"] is False


def test_render_fills_variables_and_tidies_punctuation():
    c = _ctx(first_name="Ada", booking_label="Thu 15 Oct, 16:30", schedule="Discovery Call", visits=3)
    assert o.render("Welcome back, {first_name}", c) == "Welcome back, Ada"
    assert o.render("Welcome back, {first_name}", _ctx()) == "Welcome back"
    assert o.render("{schedule} on {booking}. Visit {visits}.", c) == "Discovery Call on Thu 15 Oct, 16:30. Visit 3."
    assert o.render("Hi {first_name} , ready?", _ctx()) == "Hi, ready?"
    assert o.render("No {unknown} here", c) == "No here"
    msg = o.public_message({"id": 7, "name": "r", "message": {"title": "T", "text": "Book a call?", "replies": ["Book a call with Deep", "Why?", ""]}}, c)
    assert msg["intro"] == "Book a call?" and msg["replies"] == [{"label": "Book a call with Deep", "book": True}, {"label": "Why?", "book": False}]


def test_normalise_cleans_and_rejects_bad_rules():
    r = o.normalise({"name": "  Offer  ", "priority": "3", "cooldown_hours": 1000,
                     "trigger": {"visitor": "bogus", "page": " /Company/ ", "pages_min": "99", "dwell_s": -5, "scroll_pct": 140, "channel": ["social", "nope", "search"], "referrer": "LinkedIn"},
                     "message": {"text": "  Hello   there ", "replies": "A|B\nC|D|E|F"}})
    assert r["name"] == "Offer" and r["priority"] == 3 and r["cooldown_hours"] == 720 and r["enabled"] is True
    t = r["trigger"]
    assert t["visitor"] == "any" and t["page"] == "/Company/" and t["pages_min"] == o.MAX_PAGES and t["dwell_s"] == 0 and t["scroll_pct"] == 100
    assert t["channel"] == "social,search" and t["referrer"] == "linkedin"
    assert r["message"]["text"] == "Hello there" and r["message"]["replies"] == ["A", "B", "C", "D"]
    with pytest.raises(ValueError):
        o.normalise({"name": "", "message": {"text": "x"}})
    with pytest.raises(ValueError):
        o.normalise({"name": "x", "message": {"text": ""}})
    with pytest.raises(ValueError):
        o.normalise({"name": "x", "trigger": {"page": "company"}, "message": {"text": "y"}})   # patterns start with /
    assert o.summary({"visitor": "returning", "page": "/company/*", "pages_min": 2, "pages_match": "/company/", "dwell_s": 45}) == \
        "returning visitors · on /company/* · 2+ pages under /company/ · after 45 s on the page"
    for s in o.SEED:
        o.normalise(s)  # every starter rule is valid


def test_check_without_rules_or_database_returns_defaults(monkeypatch):
    monkeypatch.setattr(o, "default_greeting_enabled", lambda: True)
    out = o.check({"path": "/"}, "v1", rules=[], facts={})
    assert out == {"rule": None, "recheck": {}, "default": True}


# ---------------------------------------------------------------- database
def _db_up() -> bool:
    try:
        from app.db import conn, init_schema

        init_schema()
        with conn() as c:
            c.execute("SELECT 1")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_rules_fire_once_per_cooldown_and_attribute_opens_chats_and_bookings():
    from app import inbox, tracking
    from app.db import conn

    tag = uuid.uuid4().hex[:8]
    vid = f"vid-{tag}"
    sid = f"outreach-test-{tag}"
    rule = o.create_rule({"name": f"test {tag}", "priority": 1, "cooldown_hours": 24,
                          "trigger": {"page": f"/t-{tag}", "dwell_s": 5}, "message": {"text": "Hello {first_name}?", "replies": ["Book a call"]}})
    try:
        rules = [rule]
        # not long enough on the page: the loader is told when to ask again
        out = o.check({"path": f"/t-{tag}", "dwell_s": 1}, vid, rules=rules, facts={"name": "Ada"})
        assert out["rule"] is None and out["recheck"] == {"dwell_s": 5}
        out = o.check({"path": f"/t-{tag}", "dwell_s": 6, "page": f"https://x.test/t-{tag}"}, vid, rules=rules, facts={"name": "Ada"})
        assert out["rule"]["text"] == "Hello Ada?" and out["rule"]["event_id"] and out["rule"]["replies"][0]["book"] is True
        ev = out["rule"]["event_id"]
        # cooldown: same visitor, same rule, nothing fires; another visitor still gets it
        assert o.check({"path": f"/t-{tag}", "dwell_s": 9}, vid, rules=rules, facts={})["rule"] is None
        other = o.check({"path": f"/t-{tag}", "dwell_s": 9}, f"{vid}-b", rules=rules, facts={})
        assert other["rule"] is not None
        # a rule already shown on this page is skipped even without a visitor id
        assert o.check({"path": f"/t-{tag}", "dwell_s": 9, "shown": [rule["id"]]}, None, rules=rules, facts={})["rule"] is None
        # opened into a chat session that then has a message and a booking lead
        assert o.mark(ev, "opened", "someone-else", sid) is False          # a stranger cannot stamp it
        assert o.mark(ev, "opened", vid, sid) is True
        assert o.mark(other["rule"]["event_id"], "dismissed", f"{vid}-b", None) is True
        tracking.attach_visitor(sid, vid)
        inbox.log_message(sid, "user", "hi")
        tracking.touch(sid, "127.0.0.1", "test")
        with conn() as c:
            c.execute("INSERT INTO leads(name, email, reason, status, session_id) VALUES ('Ada', 'ada@example.test', 'test', 'handoff', %s)", (sid,))
            c.commit()
        st = o.stats(1)["by_rule"][rule["id"]]
        assert st == {"fired": 2, "opened": 1, "dismissed": 1, "chatted": 1, "booked": 1}
        # partial update keeps the rest; disabling drops it from the enabled list
        upd = o.update_rule(rule["id"], {"enabled": False})
        assert upd["enabled"] is False and upd["trigger"]["dwell_s"] == 5 and upd["message"]["text"] == "Hello {first_name}?"
        assert all(r["id"] != rule["id"] for r in o.enabled_rules())
        with pytest.raises(ValueError):
            o.update_rule(rule["id"], {"message": {"text": ""}})
        assert o.update_rule(10 ** 9, {"enabled": True}) is None
    finally:
        o.delete_rule(rule["id"])
        with conn() as c:
            c.execute("DELETE FROM outreach_events WHERE rule_id = %s", (rule["id"],))
            c.execute("DELETE FROM leads WHERE session_id = %s", (sid,))
            c.execute("DELETE FROM messages WHERE session_id = %s", (sid,))
            c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
            c.commit()
        o.invalidate()
    assert all(r["id"] != rule["id"] for r in o.list_rules())


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_default_greeting_switch_round_trips():
    before = o.default_greeting_enabled()
    try:
        o.set_default_greeting(False)
        assert o.default_greeting_enabled() is False
        o.set_default_greeting(True)
        assert o.default_greeting_enabled() is True
    finally:
        o.set_default_greeting(before)
