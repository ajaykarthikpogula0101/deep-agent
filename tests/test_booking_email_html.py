"""The branded booking email (app/booking/email_html.py): state-accurate copy, real links only, escaping, optional fields."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from app import mailer as mailer_mod
from app import templates
from app.booking import email_html as E
from app.config import settings

NOW = datetime(2026, 10, 9, 12, 42, tzinfo=timezone.utc)
CONFIRMED = dict(templates.SAMPLE_BOOKING, name="Harsha", email="harsha@example.com", company="xyz.com",
                 schedule_name="GTM Strategy Session: Data, AI & Revenue Acceleration", duration_min=45, visitor_tz="Asia/Kolkata",
                 start_utc=datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc), meeting_id="812 3456 7890")
PENDING = dict(CONFIRMED, method="handoff", status="pending_zoom", zoom_meeting_id=None, meeting_id=None, join_url="", passcode="",
               handoff_url="https://scheduler.zoom.us/sreedeep/gtm?firstname=Harsha&email=harsha%40example.com")


def html(booking, audience="visitor"):
    return E.render(booking, audience, dict(templates.DEFAULTS), now=NOW)


def test_confirmed_visitor_email_says_confirmed_and_links_the_meeting_and_the_booking_page():
    h = html(CONFIRMED)
    assert "Your booking is confirmed" in h and "Booking Confirmed" in h and "Awaiting Zoom Confirmation" not in h
    assert "Hi Harsha," in h and "Your GTM Strategy Session: Data, AI &amp; Revenue Acceleration has been scheduled." in h
    assert "Fri, 09 Oct 2026" in h and "6:30 PM IST" in h and "(45 minutes)" in h
    assert 'href="https://zoom.us/j/81234567890?pwd=sample"' in h and "Join meeting" in h
    assert f'href="{CONFIRMED["manage_url"]}"' in h and "View booking details" in h
    assert "ID 812 3456 7890 · Passcode 742913" in h


def test_pending_visitor_email_never_claims_confirmation_and_points_to_the_zoom_confirmation():
    h = html(PENDING)
    assert "confirmed" not in re.sub(r"<[^>]+>", " ", h).lower().replace("confirmation", "")   # no "is confirmed" anywhere
    assert "Awaiting Zoom Confirmation" in h and "Confirm your booking on Zoom" in h
    assert "Join meeting" not in h and "zoom.us/j/" not in h
    link = 'href="https://scheduler.zoom.us/sreedeep/gtm?firstname=Harsha&amp;email=harsha%40example.com"'
    assert h.count(link) == 2 and "Confirm on Zoom →" not in h       # only the button (Outlook VML + everyone else)
    assert "View booking details" not in h


def test_pending_host_email_is_a_request_with_the_true_follow_up(monkeypatch):
    h = html(PENDING, "host")
    assert "New booking request" in h and "Awaiting Zoom Confirmation" in h and "Your booking is confirmed" not in h
    assert "The visitor is still required to confirm the booking on Zoom." in h and "24 hours" in h
    assert "scheduler.zoom.us" not in h                     # the visitor's prefilled link is theirs, not the host's
    assert "View booking details" not in h and "Notes: B2B data for EU fintech" in h   # no host_url: no button
    assert PENDING["manage_url"] not in h                    # never the visitor's page (it has a Cancel button)
    u = "https://assistant.deependhq.com/host/booking/42?t=hosttoken"
    assert f'href="{u}"' in html(dict(PENDING, host_url=u), "host") and "View booking details" in html(dict(PENDING, host_url=u), "host")
    assert f"to {settings.host_email}" in h
    monkeypatch.setattr(settings, "nudge_enabled", False)
    assert "24 hours" not in html(PENDING, "host")          # no reminder promised when reminders are off


def test_confirmed_host_email():
    h = html(CONFIRMED, "host")
    assert "New booking confirmed" in h and "Booking Confirmed" in h and "Join meeting" in h
    assert "Lovelace Analytical Engines (lovelace.org)" in h  # enrichment detail line, host only
    assert "Lovelace Analytical Engines (lovelace.org)" not in html(CONFIRMED)


def test_dynamic_values_are_escaped_and_unsafe_urls_never_become_links():
    evil = dict(CONFIRMED, name='<script>alert(1)</script>', company="javascript:alert(1)", join_url="javascript:alert(1)",
                manage_url="data:text/html,x", notes='"><img src=x onerror=alert(1)>')
    for audience in ("visitor", "host"):
        h = html(evil, audience)
        assert "<script>" not in h and "&lt;script&gt;alert(1)&lt;/script&gt;" in h
        assert "onerror=alert" not in h or "&quot;&gt;&lt;img" in h
        assert 'href="javascript:' not in h and 'href="data:' not in h
        assert "View booking details" not in h and "Join meeting" not in h


def test_company_is_linked_only_when_it_is_a_domain_and_omitted_when_missing():
    assert 'href="https://xyz.com"' in html(CONFIRMED)
    assert E.company_link("https://XYZ.com/") == "https://xyz.com" and E.company_link("Acme Inc") == ""
    assert E.company_link("evil.com/path?x=1") == "" and E.company_link("javascript:alert(1)") == ""
    plain = html(dict(CONFIRMED, company="Acme Inc", company_line=""))
    assert "Acme Inc" in plain and 'href="https://acme' not in plain
    none = html(dict(CONFIRMED, company="", company_line=""))
    assert ">Company<" not in none


def test_missing_optional_fields_do_not_break_the_email():
    bare = {"name": "Ada", "email": "not-an-email", "status": "confirmed", "schedule_name": "Intro Call"}
    h = html(bare)
    assert "Intro Call" in h and ">Date<" not in h and "View booking details" not in h
    assert 'href="mailto:' not in h and "not-an-email" in h
    assert not re.search(r"\{[a-z_]+\}", re.sub(r"<style>.*?</style>", "", h, flags=re.S))  # no raw placeholders
    assert "None" not in re.sub(r"<[^>]+>", " ", h)


def test_time_formatting_uses_the_booking_timezone():
    start = datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)
    assert E.fmt_time(start.astimezone(E._tz("Asia/Kolkata"))) == "6:30 PM IST"
    assert E.fmt_time(start.astimezone(E._tz("America/New_York"))) == "9:00 AM EDT"
    assert E.fmt_time(start.astimezone(E._tz("Asia/Dubai"))) == "5:00 PM GMT+4"
    assert E.fmt_date(start) == "Fri, 09 Oct 2026"
    h = html(dict(CONFIRMED, visitor_tz="America/New_York"))
    assert "9:00 AM EDT" in h and "6:30 PM IST" in html(dict(CONFIRMED, visitor_tz="America/New_York"), "host")


def test_email_safe_markup():
    h = html(CONFIRMED)
    assert "<script" not in h and "<svg" not in h and "display:flex" not in h and "display:grid" not in h
    assert "@media only screen and (max-width:620px)" in h and "max-width:640px" in h
    assert "/static/email/hero.png" in h and "v:roundrect" in h and 'role="presentation"' in h
    assert all(re.search(r'alt="[^"]*"', tag) for tag in re.findall(r"<img [^>]+>", h))


def test_send_booking_emails_uses_the_branded_html_and_falls_back_when_it_fails(monkeypatch):
    from app.booking import email as mail

    sent = []
    m = mailer_mod.Mailer(sender=lambda to, subject, body, **k: sent.append((to, subject, body, k)) or True, sync=True)
    mail.send_booking_emails(PENDING, mailer=m)
    by_to = {s[0]: s for s in sent}
    visitor, host = by_to["harsha@example.com"], by_to[settings.host_email]
    assert "Confirm your booking on Zoom" in visitor[3]["html"] and "New booking request" in host[3]["html"]
    assert visitor[2].startswith("Hi Harsha,") and visitor[3]["attachments"][0][0] == "invite.ics"   # text part + invite unchanged

    sent.clear()
    monkeypatch.setattr(E, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    mail.send_booking_emails(PENDING, mailer=m)
    main_two = [s for s in sent if s[0] in ("harsha@example.com", settings.host_email)]
    assert len(main_two) == 2 and all(s[3]["html"] and "/static/email/hero.png" not in s[3]["html"] for s in main_two)  # simple card


def test_host_extras_from_main_guests_brief_and_a_late_update():
    b = dict(CONFIRMED, attendees=[{"name": "Ravi <b>", "email": "ravi@xyz.com"}, {"name": "", "email": "bad address"}])
    h = E.render(b, "host", dict(templates.DEFAULTS), now=NOW,
                 brief="PRE-CALL BRIEF\nLead:     Hot lead · 82/100\n• Asked about <APAC> pricing\nPlain line",
                 notice="Update: the visitor has already cancelled this call.", cta_ok=False)
    assert ">Guests<" in h and "Ravi &lt;b&gt;" in h and 'href="mailto:ravi@xyz.com"' in h and 'mailto:bad address' not in h
    assert "PRE-CALL BRIEF" in h and "Hot lead · 82/100" in h and "<li style=\"margin:0 0 3px\">Asked about &lt;APAC&gt; pricing</li>" in h and "Plain line" in h
    assert "already cancelled" in h and "View booking details" not in h
    v = E.render(b, "visitor", dict(templates.DEFAULTS), now=NOW, brief="PRE-CALL BRIEF\nLead: x")
    assert "PRE-CALL BRIEF" not in v and ">Guests<" in v                    # the brief is for the host only


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
def test_host_email_refreshes_a_pending_origin_line(monkeypatch):
    """The origin is captured at confirm time, usually before the geo lookup finished; the host copy re-reads it."""
    import uuid

    from app import store_bookings as sb
    from app.booking import email as mail
    from app.db import conn

    monkeypatch.setattr(settings, "tracking_enabled", True)
    sid = f"test-{uuid.uuid4()}"
    start = datetime(2020, 1, 6, 10, 0, tzinfo=timezone.utc)  # long past: never blocks a real slot
    b = dict(CONFIRMED, session_id=sid, origin="location pending · direct · 0 messages", attendees=[], email="ada@example.test",
             start_utc=start, end_utc=start.replace(minute=45), manage_token="t" + sid)
    bid = None
    try:
        with conn() as c:
            c.execute("""INSERT INTO sessions(session_id, channel, geo_status, city, region, country_code, messages)
                         VALUES (%s, 'direct', 'ok', 'Bengaluru', 'Karnataka', 'IN', 0)""", (sid,))
            c.commit()
        bid = b["id"] = sb.insert(b)
        sent = []
        m = mailer_mod.Mailer(sender=lambda to, subject, body, **k: sent.append((to, subject, body, k)) or True, sync=True)
        mail.send_booking_emails(b, mailer=m)
        host = next(s for s in sent if s[0] == settings.host_email)
        assert "Bengaluru, Karnataka, IN · direct" in host[2] and "location pending" not in host[2]
        assert sb.get(bid)["origin"].startswith("Bengaluru, Karnataka, IN")
    finally:
        with conn() as c:
            if bid:
                c.execute("DELETE FROM bookings WHERE id = %s", (bid,))
            c.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
            c.commit()


def test_host_email_button_opens_the_host_page_and_visitor_keeps_manage():
    u = "https://assistant.deependhq.com/host/booking/42?t=hosttoken"
    h = html(dict(CONFIRMED, host_url=u), "host")
    assert f'href="{u}"' in h and "View booking details" in h and CONFIRMED["manage_url"] not in h
    assert "View booking details" not in html(CONFIRMED, "host")      # SAMPLE_BOOKING carries no host_url
    v = html(dict(CONFIRMED, host_url=u))                             # the visitor's button stays their manage page
    assert f'href="{CONFIRMED["manage_url"]}"' in v and u not in v
    assert "host_url" not in templates.SAMPLE_BOOKING


def test_booking_emails_carry_the_host_link(monkeypatch):
    from app.booking import email as mail

    monkeypatch.setattr(settings, "link_secret", "s")
    monkeypatch.setattr(settings, "public_base_url", "https://assistant.example.com")
    monkeypatch.setattr(mail, "_refresh_origin", lambda b: b.__setitem__("origin", "Bengaluru"))
    sent = []
    m = mailer_mod.Mailer(sender=lambda to, subject, body, **k: sent.append((to, subject, body, k)) or True, sync=True)
    b = dict(templates.SAMPLE_BOOKING, manage_token="Tok")
    mail.send_booking_emails(b, mailer=m)
    host = next(s for s in sent if s[0] == settings.host_email)
    visitor = next(s for s in sent if s[0] == b["email"])
    guests = [s for s in sent if s[0] == "charles@babbage.org"]
    assert "/host/booking/42?t=" in host[3]["html"] and "View booking details" in host[3]["html"]
    assert "Booking page: https://assistant.example.com/host/booking/42?t=" in host[2] and "Where:    Bengaluru" in host[2]
    assert "/booking/42/manage" in visitor[3]["html"] and "/host/booking" not in visitor[3]["html"] + visitor[2]
    assert guests and all("/host/booking" not in g[3]["html"] + g[2] for g in guests)
    assert "host_url" not in b                                         # attach() never mutates the booking

    for send in (mail.send_reschedule_emails, mail.send_cancel_emails):
        sent.clear()
        send(dict(b, old_label_visitor="Tue 06 Oct, 10:00 (America/New_York)"), mailer=m)
        host = next(s for s in sent if s[0] == settings.host_email)
        visitor = next(s for s in sent if s[0] == b["email"])
        assert "Open booking page" in host[3]["html"] and "/host/booking/42?t=" in host[3]["html"] and "Booking page: https://" in host[2]
        assert "Open booking page" not in visitor[3]["html"] and "/host/booking" not in visitor[3]["html"] + visitor[2]

    sent.clear()
    mail.send_booking_emails(dict(templates.SAMPLE_BOOKING), mailer=m)    # no manage token: no link at all
    host = next(s for s in sent if s[0] == settings.host_email)
    assert "View booking details" not in host[3]["html"] and "Booking page:" not in host[2]
