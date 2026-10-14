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
    assert f'href="{PENDING["manage_url"]}"' in h and "Notes: B2B data for EU fintech" in h
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
    assert "https://cdn.jsdelivr.net/gh/" in h and "hero.png" in h and "cid:" not in h and "v:roundrect" in h and 'role="presentation"' in h
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
    assert len(main_two) == 2 and all(s[3]["html"] and "hero.png" not in s[3]["html"] for s in main_two)  # simple card


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


def test_icons_travel_inside_the_message_so_gmail_shows_them(monkeypatch):
    """Gmail fetches remote images through its proxy, which cannot reach a local or private host; so the icons are
    inline cid: parts of the HTML (multipart/related) and every reference has its part."""
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
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    h = E.render(dict(CONFIRMED, method="browser"), "host", dict(templates.DEFAULTS), now=NOW, images="inline")
    assert ">Zoom<" in h                                      # the browser-booked kind is a Zoom booking too
    assert mail._send("deep@example.com", "s", "Hi", html=h, attachments=[("invite.ics", "BEGIN:VCALENDAR", "text/calendar")])
    msg = captured[0]
    refs = set(re.findall(r"cid:([a-z0-9-]+\.png@cg)", h))
    related = [p for p in msg.walk() if p.get_content_type() == "multipart/related"]
    assert len(related) == 1 and related[0].get_payload()[0].get_content_type() == "text/html"
    cids = {p["Content-ID"].strip("<>") for p in msg.walk() if p.get_content_type() == "image/png"}
    assert refs and refs == cids                              # nothing broken, nothing extra
    assert any(p.get_filename() == "invite.ics" for p in msg.walk()) and msg.get_body(("plain",)).get_content().startswith("Hi")
    assert "static/email" not in h and "http://127.0.0.1" not in h


def test_preview_mode_uses_urls_and_unknown_cids_are_ignored():
    h = E.render(CONFIRMED, "visitor", dict(templates.DEFAULTS), now=NOW, images="url")
    assert "/static/email/hero.png" in h and "cid:" not in h
    assert E.inline_images('<img src="cid:../../.env@cg"><img src="cid:nope.png@cg"><img src="cid:ic-date.png@cg">') ==         [("ic-date.png@cg", (E.ASSETS / "ic-date.png").read_bytes(), "ic-date.png")]


def test_default_icons_are_public_https_files_that_exist_and_empty_setting_embeds_them(monkeypatch):
    h = html(CONFIRMED)
    urls = set(re.findall(r"(https://cdn\.jsdelivr\.net/gh/[^\"')]+?\.png)", h))
    assert urls and all(u.startswith(settings.email_assets_url + "/") for u in urls)
    assert all((E.ASSETS / u.rsplit("/", 1)[1]).is_file() for u in urls)        # every icon is in the repo (so on the CDN)
    assert "127.0.0.1" not in h and "localhost" not in h
    monkeypatch.setattr(settings, "email_assets_url", "")
    assert "cid:hero.png@cg" in html(CONFIRMED)
    monkeypatch.setattr(settings, "email_assets_url", "http://insecure.example/x")   # never plain http
    assert "cid:hero.png@cg" in html(CONFIRMED)
