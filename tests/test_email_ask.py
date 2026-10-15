"""Ask Deep from a booking email (app/email_ask.py): signed links, the panel in visitor and guest emails only, the claim
(nothing happens on a plain GET), memory binding across devices (one way), guests kept apart, booker-only actions and
the honest score. Database tests create test-<uuid> rows with @example.test addresses and delete them afterwards."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import email_ask, templates
from app import mailer as mailer_mod
from app.config import settings
from tests.test_reminders import _db_up

ORIGIN = {"origin": "http://localhost"}


@pytest.fixture(autouse=True)
def _signing(monkeypatch):
    monkeypatch.setattr(settings, "link_secret", "test-secret")
    monkeypatch.setattr(settings, "public_base_url", "https://assistant.example.com")
    monkeypatch.setattr(settings, "email_ask_enabled", True)
    monkeypatch.setattr(settings, "email_ask_target", "assistant")
    monkeypatch.setattr(settings, "email_ask_ttl_days", 30)


def _tok(link: str) -> tuple[str, str | None]:
    m = re.search(r"#t=([A-Za-z0-9_.-]+)(?:&q=([a-z_]+))?", link)
    return m.group(1), m.group(2)


# ---------------------------------------------------------------- pure: tokens, questions, links
def test_token_carries_no_address_and_breaks_when_changed():
    start = datetime.now(timezone.utc) + timedelta(days=3)
    t = email_ask.make_token(booking_id=42, email="Ada@Example.test", kind="vc", bind="mt", start=start)
    assert email_ask.TOKEN_RE.match(t) and "ada" not in t.lower() and "mt" not in t.split(".")[:4]
    assert t.split(".")[0] == "b42" and t.split(".")[1] == "b"
    g = email_ask.make_token(booking_id=42, email="grace@example.test", kind="gb", guest=True, start=start)
    assert g.split(".")[1].startswith("g") and g != t
    assert email_ask.make_token(booking_id=42, email="", kind="vc") == ""
    assert email_ask.make_token(booking_id=42, email="a@b.test", kind="zz") == ""
    assert email_ask.verify("b42.b.vc.zz.short") is None and email_ask.verify("x" * 200) is None and email_ask.verify(None) is None


def test_no_signing_key_no_token(monkeypatch):
    monkeypatch.setattr(settings, "link_secret", "")
    monkeypatch.setattr(settings, "admin_token", "")
    monkeypatch.setattr(settings, "widget_signing_secret", "")
    assert email_ask.make_token(booking_id=1, email="a@example.test", kind="vc") == ""
    assert email_ask.panel(kind="vc", email="a@example.test", pending=False, booking_id=1) is None


def test_question_sets_fit_the_email_and_state():
    for kind in email_ask.KINDS:
        for pending in (False, True):
            keys = email_ask.questions(kind, pending)
            assert 2 <= len(keys) <= 4 and all(k in email_ask.QUESTIONS for k in keys), (kind, pending)
            texts = " ".join(email_ask.QUESTIONS[k][0] for k in keys).lower()
            if pending:
                assert "join" not in texts or kind in ("vx", "gx"), (kind, keys)
            if kind.startswith("g"):
                assert all(email_ask.QUESTIONS[k][1] != "reschedule" for k in keys)   # a guest cannot move the booker's call
            if kind in ("vx", "gx"):
                assert not any(k in ("join", "prep") for k in keys)
    assert "confirmed" not in " ".join(email_ask.QUESTIONS[k][0] for k in email_ask.questions("vc", True)).lower().replace("confirm on zoom", "")


def test_links_keep_the_token_in_the_fragment(monkeypatch):
    t = email_ask.make_token(booking_id=7, email="a@example.test", kind="vc", start=datetime.now(timezone.utc))
    u = email_ask.link(t, "prep")
    assert u == f"https://assistant.example.com/ask#t={t}&q=prep" and "?" not in u
    assert email_ask.link(t, "<script>") == f"https://assistant.example.com/ask#t={t}"
    monkeypatch.setattr(settings, "email_ask_target", "site")
    assert email_ask.link(t, "prep") == f"{settings.site_base_url.rstrip('/')}/#ask-deep={t}&q=prep"
    s = email_ask.sample_panel("vc")
    assert all("#t=" not in u for _, u in s["chips"]) and s["chips"][0][1].endswith("#q=prep")


# ---------------------------------------------------------------- the panel in the emails
def _sent(fn, booking, **kw):
    out = []
    m = mailer_mod.Mailer(sender=lambda to, subject, body, **k: out.append((to, subject, body, k)) or True, sync=True)
    fn(booking, mailer=m, **kw)
    return out


def _booking(**over):
    b = dict(templates.SAMPLE_BOOKING, id=4242, manage_token="mt-x", email="ada@example.test",
             attendees=[{"name": "Grace <b>Hopper</b>", "email": "grace@example.test"}])
    b.update(over)
    return b


def test_panel_in_visitor_and_guest_emails_never_the_hosts():
    from app.booking import email as mail

    for fn in (mail.send_booking_emails, mail.send_cancel_emails, mail.send_reschedule_emails, mail.send_reminder_email):
        b = _booking(status="cancelled") if fn is mail.send_cancel_emails else _booking()
        for to, subject, body, k in _sent(fn, b):
            h = k.get("html") or ""
            if to == settings.host_email:
                assert "Ask Deep" not in h and "/ask#" not in h, (fn.__name__, subject)
            else:
                assert "s assistant anything</a>" in h and "/ask#t=" in h, (fn.__name__, to)
                assert "/ask#" not in body                       # the text part is untouched
                tokens = {_tok(u)[0] for u in re.findall(r'href="(https://assistant\.example\.com/ask#[^"]+)"', h)}
                assert len(tokens) == 1
                who = next(iter(tokens)).split(".")[1]
                assert who == ("b" if to == "ada@example.test" else who) and (to == "ada@example.test" or who.startswith("g"))
                assert "<b>Hopper</b>" not in h


def test_panel_failure_falls_back_and_text_is_unchanged(monkeypatch):
    from app.booking import email as mail

    before = [(t, s, b) for t, s, b, _ in _sent(mail.send_booking_emails, _booking())]
    monkeypatch.setattr(email_ask, "panel", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    after = _sent(mail.send_booking_emails, _booking())
    assert [(t, s, b) for t, s, b, _ in after] == before
    visitor = next(x for x in after if x[0] == "ada@example.test")
    assert "Ask Deep" not in visitor[3]["html"] and visitor[3]["html"]          # the simple card went out instead


def test_feature_off_means_no_panel(monkeypatch):
    from app.booking import email as mail

    monkeypatch.setattr(settings, "email_ask_enabled", False)
    for to, _s, _b, k in _sent(mail.send_booking_emails, _booking()):
        assert "Ask Deep" not in (k.get("html") or "")


def test_ask_panel_escapes_and_drops_unsafe_links():
    from app.booking import email_html as E

    h = E.ask_panel({"heading": "<i>Hi</i>", "line": "x", "chips": [("<b>q</b>", "https://a.example/ask#q=prep"),
                                                                   ("bad", "javascript:alert(1)")], "open": "data:text/html,x"})
    assert "&lt;i&gt;Hi&lt;/i&gt;" in h and "&lt;b&gt;q&lt;/b&gt;" in h and "javascript:" not in h and "data:" not in h
    assert "assistant anything" not in h and E.ask_panel(None) == ""


def test_about_booking_questions_skip_the_refusal_gate():
    from app.chat import ABOUT_BOOKING_RE

    for q in ("How do I join the call?", "Can I reschedule?", "When is my call now?", "Is the time set yet?"):
        assert ABOUT_BOOKING_RE.search(q), q
    assert not ABOUT_BOOKING_RE.search("What is the capital of France?")


# ---------------------------------------------------------------- the database: claim, memory, actions, score
def _client():
    from fastapi.testclient import TestClient

    from app import main

    return TestClient(main.app)


class _Rows:
    def __init__(self):
        self.sids, self.bids = [], []

    def session(self, vid: str | None, messages: int = 0, email: str | None = None) -> str:
        from app.db import conn

        sid = f"test-{uuid.uuid4()}"
        with conn() as c:
            c.execute("""INSERT INTO sessions(session_id, visitor_id, channel, geo_status, messages, user_email)
                         VALUES (%s, %s, 'direct', 'unknown', %s, %s)""", (sid, vid, messages, email))
            c.commit()
        self.sids.append(sid)
        return sid

    def booking(self, sid: str, email: str, **over) -> dict:
        from app import store_bookings

        start = datetime.now(timezone.utc) + timedelta(days=400)
        b = {"session_id": sid, "name": "Ada Test", "email": email, "schedule_slug": "discovery-call", "schedule_name": "Discovery <Call>",
             "duration_min": 30, "start_utc": start, "end_utc": start + timedelta(minutes=30), "visitor_tz": "Asia/Kolkata",
             "method": "meeting", "status": "confirmed", "manage_token": "t" + sid, "attendees": [],
             "join_url": "https://zoom.us/j/123"}
        b.update(over)
        b["id"] = store_bookings.insert(b)
        self.bids.append(b["id"])
        return store_bookings.get(b["id"])

    def cleanup(self):
        from app.db import conn

        with conn() as c:
            for bid in self.bids:
                c.execute("DELETE FROM bookings WHERE id = %s", (bid,))
                c.execute("DELETE FROM email_ask_claims WHERE booking_id = %s", (bid,))
                c.execute("DELETE FROM email_ask_events WHERE booking_id = %s", (bid,))
            for sid in self.sids:
                for t in ("email_ask_claims", "email_ask_events", "messages", "events", "session_memory", "sessions"):
                    c.execute(f"DELETE FROM {t} WHERE session_id = %s", (sid,))
            c.commit()


def _claim(client, token, sid, vid, q=None):
    return client.post("/ask/claim", json={"token": token, "q": q}, headers={**ORIGIN, "X-Session-Id": sid, "X-Visitor-Id": vid})


def _count(sql, *a):
    from app.db import conn

    with conn() as c:
        return int(c.execute(sql, a).fetchone()[0])


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_plain_get_does_nothing_and_claim_rules():
    rows, client = _Rows(), _client()
    email = f"ada-{uuid.uuid4().hex[:8]}@example.test"
    try:
        sid_a = rows.session(str(uuid.uuid4()), messages=2)
        b = rows.booking(sid_a, email, attendees=[{"name": "Grace Hopper", "email": "grace@example.test"}])
        tok = email_ask.make_token(booking_id=b["id"], email=email, kind="vc", bind=b["manage_token"], start=b["start_utc"])
        n_claims = _count("SELECT count(*) FROM email_ask_claims")
        r = client.get("/ask")                                   # what a mail scanner fetches: nothing is written
        assert r.status_code == 200 and "no-store" in r.headers["cache-control"] and r.headers["referrer-policy"] == "no-referrer"
        assert _count("SELECT count(*) FROM email_ask_claims") == n_claims

        sid_b, vid_b = f"test-{uuid.uuid4()}", str(uuid.uuid4())
        rows.sids.append(sid_b)
        r = _claim(client, tok, sid_b, vid_b, "prep")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["role"] == "booker" and j["booking"]["id"] == b["id"] and j["question"]["key"] == "prep" and j["autosend"] is True
        assert _claim(client, tok, sid_b, vid_b, "prep").json()["autosend"] is False        # once per token and question
        assert _count("SELECT count(*) FROM messages WHERE session_id = %s", sid_b) == 0     # nothing sent by the claim
        assert _count("SELECT count(*) FROM leads WHERE lower(email) = %s", email) == 0
        assert _count("SELECT count(*) FROM sessions WHERE session_id = %s AND user_email IS NULL", sid_b) == 1
        assert _count("SELECT count(*) FROM email_ask_events WHERE session_id = %s AND action = 'chip'", sid_b) == 2

        bad = tok[:-2] + ("AA" if not tok.endswith("AA") else "BB")
        assert _claim(client, bad, sid_b, vid_b).status_code == 404
        other = rows.booking(sid_a, email)                       # the same token cannot open another booking
        moved = tok.replace(f"b{b['id']}.", f"b{other['id']}.", 1)
        assert _claim(client, moved, sid_b, vid_b).status_code == 404
        assert client.post("/ask/claim", json={"token": tok}, headers={"origin": "https://evil.example", "X-Session-Id": sid_b}).status_code == 403

        old = email_ask.make_token(booking_id=b["id"], email=email, kind="vc", bind=b["manage_token"],
                                   start=datetime.now(timezone.utc) - timedelta(days=60))
        assert _claim(client, old, sid_b, vid_b).status_code == 410

        # the guest: their own token, no booking id, no booker actions
        gtok = email_ask.make_token(booking_id=b["id"], email="grace@example.test", kind="gb", guest=True,
                                    bind=b["manage_token"], start=b["start_utc"])
        sid_g, vid_g = f"test-{uuid.uuid4()}", str(uuid.uuid4())
        rows.sids.append(sid_g)
        g = _claim(client, gtok, sid_g, vid_g).json()
        assert g["role"] == "guest" and "id" not in g["booking"] and g["booking"]["booked_by"] == "Ada"
        assert all(q["action"] != "reschedule" for q in g["questions"])
        assert not email_ask.booker_owns(b["id"], vid_g, sid_g) and email_ask.booker_owns(b["id"], vid_b, sid_b)

        # rotating the booking's manage token revokes its links
        from app.db import conn

        with conn() as c:
            c.execute("UPDATE bookings SET manage_token = 'rotated' WHERE id = %s", (b["id"],))
            c.commit()
        assert email_ask.verify(tok) is None
    finally:
        rows.cleanup()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_memory_binds_one_way_and_guests_stay_apart():
    from app import memory

    rows, client = _Rows(), _client()
    email = f"ada-{uuid.uuid4().hex[:8]}@example.test"
    vid_a, vid_b, vid_g = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    try:
        sid_a = rows.session(vid_a, messages=3)                  # their earlier website chat, on their laptop
        b = rows.booking(sid_a, email, attendees=[{"name": "Grace Hopper", "email": "grace@example.test"}])
        assert not memory.profile(vid_b, None, None)["returning"]
        tok = email_ask.make_token(booking_id=b["id"], email=email, kind="vm", bind=b["manage_token"], start=b["start_utc"])
        sid_b = rows.session(vid_b)                              # the reminder opened on their phone
        assert _claim(client, tok, sid_b, vid_b).json()["memory_bound"] is True
        p = memory.profile(vid_b, None, sid_b)
        assert p["returning"] and p["visits"] >= 2
        later = rows.session(vid_b)                              # the phone, a week later, on the website
        assert memory.profile(vid_b, None, later)["returning"]
        assert sid_b not in str(memory.profile(vid_a, None, None))   # one way: the laptop never sees the phone

        gtok = email_ask.make_token(booking_id=b["id"], email="grace@example.test", kind="gr", guest=True,
                                    bind=b["manage_token"], start=b["start_utc"])
        sid_g = rows.session(vid_g)
        _claim(client, gtok, sid_g, vid_g)
        assert not memory.profile(vid_g, None, sid_g)["returning"]   # the booker's chats never reach a guest

        # booking context: live, fenced, no angle brackets from the booking
        block = email_ask.data_block(sid_b)
        assert block.startswith("Booking context (DATA") and "<booking>" in block and "Discovery  Call\"" in block
        assert "<Call>" not in block and '"can_change_here": true' in block
        assert '"can_change_here": false' in email_ask.data_block(sid_g) and email not in email_ask.data_block(sid_g)
    finally:
        rows.cleanup()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_shared_device_gets_context_but_no_history(monkeypatch):
    from app import memory

    rows, client = _Rows(), _client()
    email = f"ada-{uuid.uuid4().hex[:8]}@example.test"
    vid_a, vid_shared = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        sid_a = rows.session(vid_a, messages=2)
        b = rows.booking(sid_a, email)
        rows.session(vid_shared, messages=1, email=f"someone-{uuid.uuid4().hex[:6]}@example.test")   # another person's chat there
        tok = email_ask.make_token(booking_id=b["id"], email=email, kind="vc", bind=b["manage_token"], start=b["start_utc"])
        sid = rows.session(vid_shared)
        j = _claim(client, tok, sid, vid_shared).json()
        assert j["memory_bound"] is False and j["booking"]["id"] == b["id"]
        assert sid_a not in str(memory.profile(vid_shared, None, sid))
        assert email_ask.booker_owns(b["id"], None, sid) and not email_ask.booker_owns(b["id"], vid_shared, None)
    finally:
        rows.cleanup()


@pytest.mark.skipif(not _db_up(), reason="Postgres not reachable")
def test_score_counts_a_typed_message_never_an_open_or_a_chip():
    from app import inbox, precall
    from app.db import conn

    rows, client = _Rows(), _client()
    email = f"ada-{uuid.uuid4().hex[:8]}@example.test"
    try:
        sid_a = rows.session(str(uuid.uuid4()))
        b = rows.booking(sid_a, email)
        tok = email_ask.make_token(booking_id=b["id"], email=email, kind="vc", bind=b["manage_token"], start=b["start_utc"])
        sid = rows.session(str(uuid.uuid4()))
        _claim(client, tok, sid, str(uuid.uuid4()), "prep")
        inbox.log_message(sid, "user", "How should I prepare for this call?", reason="email_chip")
        sig = precall.gather(email, sid_a, booking=b)
        assert not sig.get("email_ask_typed")
        assert "email_ask_chat" not in [r["key"] for r in precall.score(sig)["reasons"]]
        with conn() as c:
            assert int(c.execute("""SELECT count(*) FROM messages WHERE session_id = %s AND role = 'user'
                                    AND COALESCE(reason, '') <> 'email_chip'""", (sid,)).fetchone()[0]) == 0
        email_ask.mark_typed(sid)                                # a person typed in that chat
        sc = precall.score(precall.gather(email, sid_a, booking=b))
        r = next(x for x in sc["reasons"] if x["key"] == "email_ask_chat")
        assert r["points"] == 3 and precall.CLASS["email_ask_chat"] == "observed"
    finally:
        rows.cleanup()


def test_every_email_has_date_message_id_and_the_configured_sender(monkeypatch):
    """Spam filters mark mail without Date / Message-ID (smtplib adds neither); the sender is EMAIL_FROM, logged in as
    SMTP_USER, never anything else."""
    from app.booking import email as mail

    captured = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): pass
        def login(self, *a): pass
        def send_message(self, msg): captured.append(msg)

    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "email_from", "Deep <host@example.test>")
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    assert mail._send("ada@example.test", "s", "Hi", html="<p>Hi</p>")
    msg = captured[0]
    assert msg["From"] == "Deep <host@example.test>" and msg["Date"] and msg["Message-ID"].endswith("@example.test>")
