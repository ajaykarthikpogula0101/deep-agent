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


def imgs(h: str) -> list[str]:
    """The images an email shows, by file name: only the bundled logo and host photo are allowed."""
    return sorted(re.sub(r"^cid:|@cg$|^.*/", "", s) for s in re.findall(r'<img src="([^"]+)"', h))


def html(booking, audience="visitor"):
    return E.render(booking, audience, dict(templates.DEFAULTS), now=NOW)


def test_confirmed_visitor_email_says_confirmed_and_links_the_meeting_and_the_booking_page():
    h = html(CONFIRMED)
    assert "Your call with Deep is confirmed" in h and ">Confirmed</span>" in h and 'class="st-ok"' in h
    assert "Action needed: confirm on Zoom" not in h and 'class="st-wait"' not in h
    assert "Hi Harsha," in h and "Your GTM Strategy Session: Data, AI &amp; Revenue Acceleration is booked." in h
    assert "Fri, 09 Oct 2026" in h and "6:30 PM IST" in h and "(45 minutes)" in h
    assert 'href="https://zoom.us/j/81234567890?pwd=sample"' in h and "Join meeting" in h
    # 2026-10-15: no booking-page button for visitors (the Ask Deep panel answers and moves the call); Join is the button
    assert CONFIRMED["manage_url"] not in h and "View booking details" not in h and "Join Zoom meeting" in h
    assert "ID 812 3456 7890 · Passcode 742913" in h


def test_pending_visitor_email_never_claims_confirmation_and_points_to_the_zoom_confirmation():
    h = html(PENDING)
    assert "confirmed" not in re.sub(r"<[^>]+>", " ", h).lower().replace("confirmation", "")   # no "is confirmed" anywhere
    assert "Action needed: confirm on Zoom" in h and 'class="st-wait"' in h and "Confirm your time on Zoom" in h
    assert "Join meeting" not in h and "zoom.us/j/" not in h
    link = 'href="https://scheduler.zoom.us/sreedeep/gtm?firstname=Harsha&amp;email=harsha%40example.com"'
    assert h.count(link) == 2 and "Confirm on Zoom →" not in h       # only the button (Outlook VML + everyone else)
    assert "View booking details" not in h


def test_pending_host_email_is_a_request_with_the_true_follow_up(monkeypatch):
    h = html(PENDING, "host")
    assert "New booking request" in h and "Action needed: confirm on Zoom" in h and "is confirmed" not in h
    assert "The visitor is still required to confirm the booking on Zoom." in h and "24 hours" in h
    assert "scheduler.zoom.us" not in h                     # the visitor's prefilled link is theirs, not the host's
    assert "View booking details" not in h and ">Notes<" in h and "B2B data for EU fintech" in h   # no host_url: no button
    assert PENDING["manage_url"] not in h                    # never the visitor's page (it has a Cancel button)
    u = "https://assistant.deependhq.com/host/booking/42?t=hosttoken"
    assert f'href="{u}"' in html(dict(PENDING, host_url=u), "host") and "View booking details" in html(dict(PENDING, host_url=u), "host")
    assert f"to {settings.host_email}" not in h               # no "Sent from X to Y" machine line (2026-10-15)
    monkeypatch.setattr(settings, "nudge_enabled", False)
    assert "24 hours" not in html(PENDING, "host")          # no reminder promised when reminders are off


def test_confirmed_host_email():
    h = html(CONFIRMED, "host")
    assert "New booking confirmed" in h and ">Confirmed</span>" in h and 'class="st-ok"' in h and "Join meeting" in h
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
    assert "@media only screen and (max-width:620px)" in h and "max-width:600px" in h
    assert imgs(h) == ["host.png", "logo.png"] and "cid:" not in h and "v:roundrect" in h   # the logo and Deep's photo only
    assert all(re.search(r'alt="[^"]*"', tag) for tag in re.findall(r"<img [^>]+>", h))


def test_send_booking_emails_uses_the_branded_html_and_falls_back_when_it_fails(monkeypatch):
    from app.booking import email as mail

    sent = []
    m = mailer_mod.Mailer(sender=lambda to, subject, body, **k: sent.append((to, subject, body, k)) or True, sync=True)
    mail.send_booking_emails(PENDING, mailer=m)
    by_to = {s[0]: s for s in sent}
    visitor, host = by_to["harsha@example.com"], by_to[settings.host_email]
    assert "Confirm your time on Zoom" in visitor[3]["html"] and "New booking request" in host[3]["html"]
    assert visitor[2].startswith("Hi Harsha,") and visitor[3]["attachments"][0][0] == "invite.ics"   # text part + invite unchanged

    sent.clear()
    monkeypatch.setattr(E, "render", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    mail.send_booking_emails(PENDING, mailer=m)
    main_two = [s for s in sent if s[0] in ("harsha@example.com", settings.host_email)]
    assert len(main_two) == 2 and all(s[3]["html"] and "hero.png" not in s[3]["html"] and "dm-card" not in s[3]["html"]
                                      for s in main_two)  # simple card


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
    assert CONFIRMED["manage_url"] not in v and u not in v and "View booking details" not in v   # Join is the visitor's button
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
    assert "/booking/42/manage" in visitor[2] and "/booking/42/manage" not in visitor[3]["html"]      # text part keeps it
    assert "/host/booking" not in visitor[3]["html"] + visitor[2]
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


PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")   # a 1x1 test image


def test_inline_images_travel_inside_the_message_so_gmail_shows_them(monkeypatch, tmp_path):
    """No current email uses images, but the delivery mechanism stays: an email that references cid: images (here a
    test image in a stand-in static/email folder) gets them as inline parts of the HTML (multipart/related), every
    reference with its part and nothing extra."""
    from app.booking import email as mail

    (tmp_path / "test.png").write_bytes(PNG)
    monkeypatch.setattr(E, "ASSETS", tmp_path)
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
    assert "cid:" not in h and E.inline_images(h) == []       # the Ledger design itself has no images
    img = E._img(E.image_base(CONFIRMED, "inline"), "test.png", 20, alt="Test")
    assert 'alt="Test"' in img and 'src="cid:test.png@cg"' in img
    h = h.replace("</body>", img + "</body>")
    assert mail._send("deep@example.com", "s", "Hi", html=h, attachments=[("invite.ics", "BEGIN:VCALENDAR", "text/calendar")])
    msg = captured[0]
    refs = set(re.findall(r"cid:([a-z0-9-]+\.png@cg)", h))
    related = [p for p in msg.walk() if p.get_content_type() == "multipart/related"]
    assert len(related) == 1 and related[0].get_payload()[0].get_content_type() == "text/html"
    cids = {p["Content-ID"].strip("<>") for p in msg.walk() if p.get_content_type() == "image/png"}
    assert refs == {"test.png@cg"} and refs == cids           # nothing broken, nothing extra
    assert any(p.get_filename() == "invite.ics" for p in msg.walk()) and msg.get_body(("plain",)).get_content().startswith("Hi")
    assert "static/email" not in h and "http://127.0.0.1" not in h


def test_preview_mode_uses_urls_and_unknown_cids_are_ignored(monkeypatch, tmp_path):
    (tmp_path / "test.png").write_bytes(PNG)
    monkeypatch.setattr(E, "ASSETS", tmp_path)
    src = E._src(E.image_base(dict(CONFIRMED, host_url=""), "url"), "test.png")
    assert src.endswith("/static/email/test.png") and "cid:" not in src      # the running app's own copy
    assert E.inline_images('<img src="cid:../../.env@cg"><img src="cid:nope.png@cg"><img src="cid:test.png@cg">') ==         [("test.png@cg", PNG, "test.png")]


def test_hosted_images_come_from_a_public_https_folder_and_an_empty_setting_embeds_them(monkeypatch):
    monkeypatch.setattr(settings, "email_assets_url", "https://cdn.example.com/static/email")
    assert E.image_base(CONFIRMED) == "https://cdn.example.com/static/email"
    assert E._src(E.image_base(CONFIRMED), "test.png") == "https://cdn.example.com/static/email/test.png"
    assert E.image_base(CONFIRMED, "inline") == E.CID                       # inline wins over hosted when asked
    monkeypatch.setattr(settings, "email_assets_url", "")
    assert E.image_base(CONFIRMED) == E.CID
    monkeypatch.setattr(settings, "email_assets_url", "http://insecure.example/x")   # never plain http
    assert E.image_base(CONFIRMED) == E.CID
    for audience, want in (("visitor", {"logo.png@cg", "host.png@cg"}), ("host", {"logo.png@cg"})):   # the only cid: parts
        assert set(re.findall(r"cid:([^\"]+)", html(PENDING, audience))) == want


# ---------------------------------------------------------------- the Ledger visitor confirmation (#1)
def _text(h):
    """What a reader sees: tags, the head (title, styles) and the hidden preheader filler removed."""
    body = h.split("<body", 1)[1]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body.replace("&#847;&zwnj;&nbsp;", "")))


def test_visitor_confirmation_states_differ_in_pill_tile_note_and_button():
    c, p = html(CONFIRMED), html(PENDING)
    # confirmed: green state word, the meeting link + ID, Join Zoom as the button, Add to calendar
    assert 'class="st-ok"' in c and 'class="st-wait"' not in c
    assert ">Join<" in c and "Join meeting</a>" in c and "Join from the button below at the scheduled time." in c
    assert c.count('href="https://zoom.us/j/81234567890?pwd=sample"') >= 3                # Join row + button (VML + link)
    assert CONFIRMED["manage_url"] not in c and "Add to calendar" in c and "calendar.google.com/calendar/render?" in c
    assert "outlook.live.com/calendar" in c and 'href="https://assistant.deependhq.com/booking/42/ics?t=sample"' in c
    # pending: orange "action needed", no meeting at all, the held note, the prefilled Zoom link as the only button
    assert 'class="st-wait"' in p and 'class="st-ok"' not in p and "Add to calendar" not in p
    assert ">Join<" not in p and ">Meeting<" not in p and "Passcode" not in p and "ID 812" not in p
    assert "Your meeting link is sent as soon as you confirm." in p and "We’re holding this time for your GTM Strategy Session" in p
    assert PENDING["manage_url"] not in p and "View booking details" not in p
    # pending without a prefilled link: no button at all (no booking page for visitors), still never "confirmed"
    no_link = html(dict(PENDING, handoff_url=""))
    assert PENDING["manage_url"] not in no_link and "Confirm on Zoom" not in no_link and "v:roundrect" not in no_link
    assert "confirmed" not in _text(no_link).lower().replace("confirmation", "")
    assert "v:roundrect" not in html(dict(PENDING, handoff_url="", manage_url=""))      # nothing to link: no button


def test_visitor_confirmation_keeps_the_copy_word_for_word():
    tpl = dict(templates.DEFAULTS)
    for b, confirmed in ((CONFIRMED, True), (PENDING, False)):
        v = templates.build_vars(templates.booking_to_lead(b), tpl)
        copy = E._copy("visitor", confirmed, v, tpl)
        h = html(b)
        for key in ("eyebrow", "heading", "intro2", "status", "preheader"):
            assert E.esc(copy[key]) in h, key
        assert all(E.esc(t) in h for t in copy["intro"])
        assert f"<title>{E.esc(copy['heading'])}</title>" in h
        assert E.esc(E.FOOTER_NOTE["visitor"]) in h and "Sent from" not in h and "deependhq.com</div>" in h


def test_visitor_confirmation_event_card_facts():
    h = html(dict(CONFIRMED, attendees=[{"name": "Ravi", "email": "ravi@xyz.com"}]))
    t = _text(h)
    assert "OCT" in t and " 9 " in t and "Fri" in t                               # the date tile, visitor time zone
    assert "Fri, 09 Oct 2026 6:30 PM IST (45 minutes)" in t
    assert "Platform Zoom" in t and "Attendee Harsha harsha@example.com" in t and "Company xyz.com" in t
    assert "Guests Ravi · ravi@xyz.com" in t and 'href="mailto:ravi@xyz.com"' in h
    assert "Notes" not in t and "B2B data for EU fintech" not in t                 # notes stay in the host copy
    late = html(dict(CONFIRMED, start_utc=datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)))
    assert "Sat, 10 Oct 2026" in late and ">10</div>" in late and "1:30 AM IST" in late   # the tile follows visitor_tz


def test_visitor_confirmation_without_a_start_has_no_tile_and_no_guessing():
    h = html({"name": "Ada", "email": "ada@example.com", "status": "confirmed", "schedule_name": "Intro Call"})
    assert 'height="3"' not in h and ">Platform<" not in h and ">When<" not in h and "minutes)" not in h
    assert "Intro Call" in h and ">Attendee<" in h


def test_visitor_confirmation_design_system_markup():
    h = html(CONFIRMED)
    assert h.count("<style>") == 2                                                # Gmail dropping one keeps the other
    assert '<meta name="color-scheme" content="light dark">' in h and "@media (prefers-color-scheme:dark)" in h
    assert "[data-ogsc] .dm-ink" in h and "[data-ogsb] .dm-card" in h              # Outlook.com dark mode
    css = "".join(re.findall(r"<style>(.*?)</style>", h, flags=re.S))
    assert len(css.encode()) < 3000                                               # small enough to survive clipping rules
    assert len(h.encode()) < 80_000                                               # far below Gmail's 102 KB clip
    assert 'width="600"' in h and "<!--[if mso]>" in h                              # the Outlook ghost table
    assert "Inter" not in h and "fonts.googleapis" not in h and imgs(h) == ["host.png", "logo.png"] and "url(" not in h
    assert "#101E50" not in h and "Strategy · Growth · Impact" not in h            # nothing of the previous design
    pre = re.search(r"<body[^>]*>\s*<div[^>]*>(.*?)</div>", h, flags=re.S).group(1)
    assert pre == E.esc("GTM Strategy Session: Data, AI & Revenue Acceleration on Fri 09 Oct, 18:30 (Asia/Kolkata). "
                        "Join details and calendar invite inside.")
    assert "#5546F7" not in h and "#F26722" in h                                  # Champions Orange, not the old violet


def test_the_logo_is_the_only_image_hosted_or_inside_the_message(monkeypatch):
    """The Champions Group logo (static/email/logo.png): from EMAIL_ASSETS_URL (https), else a cid: part of the message;
    alt text is the brand, so it reads with images blocked; another brand gets its name as text."""
    h = html(CONFIRMED)
    assert imgs(h) == ["host.png", "logo.png"] and f'src="{settings.email_assets_url}/logo.png"' in h and 'alt="Champions Group"' in h
    assert f'src="{settings.email_assets_url}/host.png"' in h and 'alt="Sreedeep Surapaneni"' in h and ">Sreedeep Surapaneni</div>" in h
    assert (E.ASSETS / "logo.png").is_file() and (E.ASSETS / "host.png").is_file() and E.inline_images(h) == []
    monkeypatch.setattr(settings, "email_assets_url", "")
    h = html(CONFIRMED)
    assert 'src="cid:logo.png@cg"' in h and sorted(x[0] for x in E.inline_images(h)) == ["host.png@cg", "logo.png@cg"]
    monkeypatch.setattr(settings, "email_assets_url", "http://insecure.example/x")      # never plain http
    assert 'src="cid:logo.png@cg"' in html(CONFIRMED)
    other = E.render(CONFIRMED, "visitor", dict(templates.DEFAULTS, brand_default="Acme"), now=NOW)
    assert "logo.png" not in other and ">Acme</div>" in other
    assert E.image_base(CONFIRMED, "inline") == E.CID and E.image_base(CONFIRMED, "url").endswith("/static/email")


def test_visitor_brand_monogram_and_brand_are_escaped():
    tpl = dict(templates.DEFAULTS, brand_default="<b>Acme</b> & Co")
    h = E.render(CONFIRMED, "visitor", tpl, now=NOW)
    assert "<b>Acme" not in h and "&lt;b&gt;Acme&lt;/b&gt; &amp; Co" in h and ">&lt;</td>" not in h   # a wordmark, no monogram


def test_buttons_and_time_change_components():
    b = E.buttons([("Join Zoom", "https://zoom.us/j/1"), ("Open booking page", "https://x.example/host/booking/1?t=a&b=c"),
                   ("Bad", "javascript:alert(1)"), None])
    assert b.count('href="https://zoom.us/j/1"') == 2 and b.count('href="https://x.example/host/booking/1?t=a&amp;b=c"') == 2
    assert "Bad" not in b and "javascript" not in b
    assert 'class="btn"' in b and 'class="btn btn2"' in b and b.index("Join Zoom") < b.index("Open booking page")
    assert E.buttons([("Nothing", "")]) == "" and E.buttons([]) == ""
    w = E.time_change("Tue 06 Oct, 10:00 <old>", "Wed 07 Oct, 09:30")
    assert ">Was<" in w and ">Now<" in w and "line-through" in w and "&lt;old&gt;" in w
    assert E.notice("") == "" and "&lt;b&gt;" in E.notice("<b>")
    assert ">Cancelled</span>" in E.pills([("off", "")]) and E.pills([("move", ""), ("wait", "")]).count("&middot;") == 1


def test_visitor_extras_host_card_phone_agenda_and_footer_address(monkeypatch):
    """2026-10-15: the host row (name, title, optional https photo), joining by phone when the meeting ID is known,
    "What to expect" for the call type, the postal address in the footer, and an honest next step without a Zoom link."""
    h = html(CONFIRMED)
    assert ">Host<" in h and "Founder &amp; CEO, Champions Group" in h and "/host.png" in h       # the bundled photo
    assert ">By phone<" in h and 'href="https://zoom.us/zoomconference"' in h and "meeting ID 812 3456 7890" in h
    assert "What to expect" in h and "Clear next steps, if there is a fit" in h                     # by the slug (discovery-call)
    assert ">By phone<" not in html(PENDING) and "Join from the button below" in h
    monkeypatch.setattr(settings, "host_photo_url", "https://cdn.example.com/deep.jpg")
    monkeypatch.setattr(settings, "host_title", "<b>CMO</b>")
    monkeypatch.setattr(settings, "email_postal_address", "1 Example Road, Bengaluru <560001>")
    h = html(CONFIRMED)
    assert '<img src="https://cdn.example.com/deep.jpg" width="40" height="40" alt="Sreedeep Surapaneni"' in h and "&lt;b&gt;CMO&lt;/b&gt;" in h
    assert "1 Example Road, Bengaluru &lt;560001&gt;" in h
    monkeypatch.setattr(settings, "host_photo_url", "http://insecure.example/deep.jpg")
    assert "insecure.example" not in html(CONFIRMED) and "/host.png" in html(CONFIRMED)          # https only: else the bundled photo
    browser = html(dict(CONFIRMED, join_url="", zoom_meeting_id=None, meeting_id=None, passcode="", method="browser"))
    assert "Zoom sends the meeting link in its own invitation" in browser and "Join from the button below" not in browser
    assert "Join Zoom meeting" not in browser and ">By phone<" not in browser
