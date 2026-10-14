"""Outbound email over SMTP: the host brief and the visitor confirmation, both rendered from the editable
templates in app/templates.py. If SMTP is not configured the message is logged and the lead row still exists."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Callable

from app import templates
from app.config import settings

log = logging.getLogger("booking.email")


def is_pending(booking: dict[str, Any]) -> bool:
    """The time is held and still has to be confirmed on Zoom. The one rule every booking email (text, buttons, HTML) follows."""
    return booking.get("status") == "pending_zoom" or booking.get("method") == "handoff"


def _html(make: Callable[[], str], subject: str, body: str, cta: tuple[str, str] | None = None, *, audience: str = "visitor",
          actions: list[tuple[str, str]] | None = None) -> str:
    """The Ledger HTML part (app/booking/email_html.py); the simple card if it ever fails, so the mail still goes out."""
    try:
        return make()
    except Exception as e:
        log.error("booking email html failed, sending the simple version: %s", e)
        return templates.html_wrap(subject, body, cta, audience=audience, actions=actions)


def render_brief(lead: dict) -> tuple[str, str]:
    """Host brief (subject, body) for a lead dict. Kept as the public name used by scripts and tests."""
    return templates.render_host(lead)


def render_visitor(lead: dict) -> tuple[str, str] | None:
    return templates.render_visitor(lead)


def _send(to: str, subject: str, body: str, reply_to: str | None = None, html: str | None = None,
          attachments: list[tuple[str, bytes | str, str]] | None = None) -> bool:
    """Plain text, optionally with an HTML alternative and attachments [(filename, data, mime)] such as an .ics invite."""
    if not settings.smtp_host:
        log.warning("SMTP not configured; email NOT sent. To=%s Subject=%r", to, subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.email_from
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
        if "cid:" in html:  # the booking email's icons travel inside the message (app/booking/email_html.py)
            from app.booking.email_html import inline_images

            part = msg.get_body(preferencelist=("html",))
            for cid, data, name in inline_images(html):
                part.add_related(data, maintype="image", subtype="png", cid=f"<{cid}>", disposition="inline", filename=name)
    for name, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        raw = data.encode("utf-8") if isinstance(data, str) else data
        params = {"method": "PUBLISH"} if subtype == "calendar" else {}
        msg.add_attachment(raw, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=name, params=params)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.error("email send failed (to %s): %s", to, e)
        return False


def send_plain(to: str, subject: str, body: str) -> bool:
    """Any other text email (weekly digest)."""
    return _send(to, subject, body)


def send_host_brief(lead: dict) -> bool:
    subject, body = render_brief(lead)
    return _send(settings.host_email, subject, body, reply_to=lead.get("email"))


def send_visitor_confirmation(lead: dict) -> bool:
    """'Thank you for booking with {brand}' (or the hand-over acknowledgement). Replies go to the host."""
    rendered = render_visitor(lead)
    if not rendered or not lead.get("email"):
        return False
    subject, body = rendered
    if lead.get("status") == "nudge":  # only the 24 h reminder has an HTML part; the hand-off and hand-over emails stay text
        return _send(lead["email"], subject, body, reply_to=settings.host_email, html=_nudge_html(lead, subject, body))
    return _send(lead["email"], subject, body, reply_to=settings.host_email)


def _nudge_html(lead: dict, subject: str, body: str) -> str:
    from app.booking import email_html

    return _html(lambda: email_html.render_nudge(lead, subject, body), subject, body,
                 ("Confirm on Zoom", lead.get("handoff_url") or ""))


def attendee_notice(booking: dict[str, Any], guest: dict[str, str], kind: str, tpl: dict[str, str] | None = None) -> tuple[str, str, tuple[str, str] | None]:
    """(subject, body, call-to-action) for one extra guest: "booked" (invited), "moved", "cancelled" or "reminder".
    Written to the guest, never as if they had booked themselves."""
    tpl = tpl or templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    first = (guest.get("name") or "").strip().split(" ")[0] or "there"
    booker = v["name"] or "A colleague"
    pending = is_pending(booking)
    others = [g for g in (booking.get("attendees") or []) if g.get("email") and g.get("email") != guest.get("email")]
    with_line = ", ".join([booker] + [g.get("name") or g.get("email") for g in others])
    facts = (f"Call:     {v['title']} ({v['duration']} min) with {v['host_name']}\n" if v["duration"] else f"Call:     {v['title']} with {v['host_name']}\n")
    zoom = (f"Zoom:     {v['join_url']}\n" + (f"{v['meeting_line']}\n" if v["meeting_line"] else "")) if v["join_url"] else ""
    if kind == "booked":
        subject = f"{booker} invited you: {v['title']} with {v['host_name']} on {v['date_visitor']}"
        body = (f"Hi {first},\n\n{booker} added you to a call with {v['host_name']}.\n\n{facts}When:     {v['date_visitor']}\n"
                f"With:     {with_line}\n{zoom}" + (f"Topic:    {v['reason']}\n" if v["reason"] else "") + "\n"
                + ("The time is held while it is confirmed on Zoom; Zoom sends the meeting link once it is final.\n\n" if pending else "")
                + f"The calendar invite is attached. If you can't make it, just reply to this email.\n\nSee you there,\n{v['host_name']}\n{v['site']}\n")
    elif kind == "moved":
        subject = f"Moved: {v['title']} with {v['host_name']} now on {v['date_visitor']}"
        body = (f"Hi {first},\n\nThe call {booker} added you to has a new time.\n\n{facts}"
                + (f"Was:      {v['old_date_visitor']}\n" if v["old_date_visitor"] else "")
                + f"Now:      {v['date_visitor']}\n{zoom}\nThe updated calendar invite is attached.\n\nSee you then,\n{v['host_name']}\n{v['site']}\n")
    elif kind == "cancelled":
        subject = f"Cancelled: {v['title']} with {v['host_name']} on {v['date_visitor']}"
        body = (f"Hi {first},\n\nThe call {booker} added you to has been cancelled, so there is nothing in your diary for it any more.\n\n"
                f"{facts}Was:      {v['date_visitor']}\n\nAll the best,\n{v['host_name']}\n{v['site']}\n")
    else:
        subject = f"Reminder: {v['title']} with {v['host_name']} tomorrow, {v['date_visitor']}"
        body = (f"Hi {first},\n\nA quick reminder that the call {booker} added you to is tomorrow.\n\n{facts}When:     {v['date_visitor']}\n"
                f"With:     {with_line}\n{zoom}\nLooking forward to it,\n{v['host_name']}\n{v['site']}\n")
    cta = ("Join Zoom", booking["join_url"]) if booking.get("join_url") and kind != "cancelled" else None
    return subject, body, cta


def send_attendee_emails(booking: dict[str, Any], kind: str, mailer=None, attachments: list | None = None) -> int:
    """Queue the notice for every extra guest on the booking. Returns how many were queued."""
    from app import mailer as m

    guests = [g for g in (booking.get("attendees") or []) if g.get("email")]
    if not guests:
        return 0
    mailer = mailer or m.default
    tpl = templates.get_templates()
    from app.booking import email_html

    for g in guests:
        subject, body, cta = attendee_notice(booking, g, kind, tpl)
        html = _html(lambda: email_html.render_guest(booking, g, kind, subject, body, tpl, pending=is_pending(booking), actions=[cta]),
                     subject, body, cta)
        mailer.enqueue(g["email"], subject, body, html=html, attachments=attachments,
                       reply_to=settings.host_email, kind=f"attendee_{kind}", ref=booking.get("id"))
    return len(guests)


def _current(booking: dict[str, Any]) -> dict[str, Any] | None:
    """The booking as stored now (None when it has no id or the read fails)."""
    if not booking.get("id"):
        return None
    try:
        from app import store_bookings

        return store_bookings.get(int(booking["id"]))
    except Exception:
        return None


def _refresh_origin(booking: dict[str, Any]) -> None:
    """The origin line was captured at confirm time, often before the geo lookup finished ('location pending').
    Re-read it for the host copy and store the newer line on the booking. Never raises."""
    if not booking.get("session_id"):
        return
    try:
        from app import tracking
        from app.db import conn

        fresh = tracking.describe_session(booking["session_id"])
        if not fresh or fresh == booking.get("origin"):
            return
        booking["origin"] = fresh
        if booking.get("id"):
            with conn() as c:
                c.execute("UPDATE bookings SET origin = %s WHERE id = %s AND session_id = %s",
                          (fresh, booking["id"], booking["session_id"]))
                c.commit()
    except Exception as e:
        log.warning("origin refresh failed: %s", e)


def send_booking_emails(booking: dict[str, Any], mailer=None, with_brief: bool = False) -> None:
    """Visitor confirmation + host 'New booking', both with the .ics invite, queued on the background mailer.
    `with_brief`: the host copy waits on a worker thread for the pre-call brief (app/precall.py) and carries it; the
    visitor and guest emails never wait. Off in tests and scripts, on for real bookings (PRECALL_ENABLED)."""
    from app import mailer as m
    from app.booking import ics

    mailer = mailer or m.default
    tpl = templates.get_templates()
    invite = ics.build(booking, tpl.get("host_name") or "Deep")
    att = [("invite.ics", invite, "text/calendar")]
    v = templates.render_booking_visitor(booking, tpl)
    if v and booking.get("email"):
        mailer.enqueue(booking["email"], v[0], v[1], html=_booking_html(booking, "visitor", tpl, v, pending=is_pending(booking)), attachments=att,
                       reply_to=settings.host_email, kind="booking_visitor", ref=booking.get("id"))

    def host(brief: dict | None) -> None:
        from app import host_page, precall

        _refresh_origin(booking)
        hb = host_page.attach(booking)  # after the refresh, so the host copy carries the fresh Where line
        s, b = templates.render_booking_host(hb, tpl)
        if brief:
            s += f" · {precall.headline(brief)}" if brief.get("label") in ("hot", "warm") else ""
            b = b.rstrip("\n") + "\n\n" + precall.text(brief)
        notice = ""
        if with_brief:  # the brief took a while: say so if the visitor moved or cancelled meanwhile (their email went out first)
            now = _current(booking)
            if now and now.get("status") == "cancelled":  # the button stays: the booking page shows the Cancelled state
                notice = "Update: the visitor has already cancelled this call."
                s, b = s + " (since cancelled)", notice + "\n\n" + b
            elif now and now.get("rescheduled_at"):
                notice = "Update: the visitor has since moved this call; the time below is the original one."
                s, b = s + " (since moved)", notice + "\n\n" + b
        html = _booking_html(hb, "host", tpl, (s, b), brief=precall.text(brief) if brief else "", notice=notice, pending=is_pending(booking))
        mailer.enqueue(settings.host_email, s, b, html=html, attachments=att,
                       reply_to=booking.get("email"), kind="booking_host", ref=booking.get("id"))

    if with_brief:
        from app import precall

        precall.host_booking_email_async(booking, host)
    else:
        host(None)
    send_attendee_emails(booking, "booked", mailer, att)


def send_reschedule_emails(booking: dict[str, Any], mailer=None) -> None:
    """Both sides hear about the new time; the visitor copy carries a fresh .ics invite."""
    from app import mailer as m
    from app.booking import email_html, ics

    mailer = mailer or m.default
    tpl = templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    was = booking.get("old_label_visitor") or "the earlier time"
    pending = is_pending(booking)
    subject = f"Moved: {v['title']} now on {v['date_visitor']}"
    att = [("invite.ics", ics.build(booking, tpl.get("host_name") or "Deep"), "text/calendar")]
    cta = ("Confirm on Zoom", booking["handoff_url"]) if pending and booking.get("handoff_url") else (("Join Zoom", booking["join_url"]) if booking.get("join_url") else None)
    # the visitor copy is the editable "visitor_rescheduled" template (Console -> Emails); the link rides as `link` for the next step
    r = templates.render_booking_visitor(dict(booking, status="rescheduled", booking_status="pending_zoom" if pending else "confirmed",
                                              old_label_visitor=was, old_label_host=booking.get("old_label_host") or ""), tpl)
    if r and booking.get("email"):
        html = _html(lambda: email_html.render_moved(booking, "visitor", r[0], r[1], tpl, pending=pending, actions=[cta]), r[0], r[1], cta)
        mailer.enqueue(booking["email"], r[0], r[1], html=html, attachments=att,
                       reply_to=settings.host_email, kind="reschedule_visitor", ref=booking.get("id"))
    from app import host_page

    hu = host_page.link(booking)
    body_h = (f"The visitor moved their call.\n\nName:   {v['name']}\nEmail:  {v['email']}\nCall:   {v['title']}\nWas:    {was}\nNow:    {v['date']}\n"
              + ("Status: held, waiting for the visitor to confirm on Zoom\n" if pending else "Status: rescheduled on Zoom Scheduler\n")
              + (f"Booking page: {hu}\n" if hu else ""))
    actions = [a for a in (("Open booking page", hu), ("Join Zoom", booking.get("join_url") if not pending else "")) if a[1]]
    html_h = _html(lambda: email_html.render_moved(booking, "host", subject, body_h, tpl, pending=pending, actions=actions),
                   subject, body_h, None, audience="host", actions=actions)
    mailer.enqueue(settings.host_email, f"[{v['brand']}] Moved: {v['name']} · {v['title']} · {v['date']}", body_h,
                   html=html_h, attachments=att, reply_to=booking.get("email"),
                   kind="reschedule_host", ref=booking.get("id"))
    send_attendee_emails(dict(booking, old_label_visitor=was), "moved", mailer, att)


def _booking_html(booking: dict[str, Any], audience: str, tpl: dict[str, str], text: tuple[str, str], **extra: Any) -> str:
    """The branded booking email (app/booking/email_html.py); the simple card if it ever fails, so the mail still goes out."""
    from app.booking import email_html

    try:
        return email_html.render(booking, audience, tpl, **extra)
    except Exception as e:
        log.error("booking email html failed, sending the simple version: %s", e)
        return templates.html_wrap(text[0], text[1], None, audience=audience)


def send_cancel_emails(booking: dict[str, Any], mailer=None) -> None:
    from app import mailer as m
    from app.booking import email_html

    mailer = mailer or m.default
    tpl = templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    from app import host_page

    hu = host_page.link(booking)
    subject = f"Cancelled: {v['title']} on {v['date_visitor']}"
    body_h = (f"Cancelled by the visitor.\n\nName:   {v['name']}\nEmail:  {v['email']}\nCall:   {v['title']}\nWas:    {v['date']}\n"
              + (f"Note:   {booking['zoom_note']}\n" if booking.get("zoom_note") else "")
              + (f"Booking page: {hu}\n" if hu else ""))
    r = templates.render_booking_visitor(dict(booking, status="cancelled", booking_status="cancelled"), tpl)  # editable "visitor_cancelled"
    if r and booking.get("email"):
        cta = ("Book a new time", settings.site_base_url)
        html = _html(lambda: email_html.render_cancelled(booking, "visitor", r[0], r[1], tpl, actions=[cta]), r[0], r[1], cta)
        mailer.enqueue(booking["email"], r[0], r[1], html=html,
                       reply_to=settings.host_email, kind="cancel_visitor", ref=booking.get("id"))
    actions = [("Open booking page", hu)] if hu else None
    html_h = _html(lambda: email_html.render_cancelled(booking, "host", subject, body_h, tpl, actions=actions or []),
                   subject, body_h, None, audience="host", actions=actions)
    mailer.enqueue(settings.host_email, f"[{v['brand']}] {subject} · {v['name']}", body_h,
                   html=html_h,
                   reply_to=booking.get("email"), kind="cancel_host", ref=booking.get("id"))
    send_attendee_emails(booking, "cancelled", mailer)


def send_reminder_email(booking: dict[str, Any], mailer=None) -> bool:
    """The day-before reminder (app/reminders.py): the editable "visitor_reminder" template with the join or confirm link.
    Returns False when the template is disabled or the booking has no email."""
    from app import mailer as m

    from app.booking import email_html

    mailer = mailer or m.default
    tpl = templates.get_templates()
    pending = is_pending(booking)
    r = templates.render_booking_visitor(dict(booking, status="reminder", booking_status="pending_zoom" if pending else "confirmed"), tpl)
    if not r or not booking.get("email"):
        return False
    cta = ("Confirm on Zoom", booking["handoff_url"]) if pending and booking.get("handoff_url") else (("Join Zoom", booking["join_url"]) if booking.get("join_url") else None)
    html = _html(lambda: email_html.render_reminder(booking, r[0], r[1], tpl, pending=pending, actions=[cta]), r[0], r[1], cta)
    mailer.enqueue(booking["email"], r[0], r[1], html=html, reply_to=settings.host_email,
                   kind="reminder_visitor", ref=booking.get("id"))
    send_attendee_emails(booking, "reminder", mailer)
    return True


def send_test(kind: str) -> dict:
    """Console → Emails → 'Send test': the sample lead rendered with the current templates, to the host inbox."""
    if kind == "host_booking":  # the button opens /host/booking/sample on this deployment
        from app import host_page

        sample = dict(templates.SAMPLE_BOOKING, host_url=host_page.sample_link())
        subject, body = templates.render_booking_host(sample)
        html = _booking_html(sample, "host", templates.get_templates(), (subject, body), pending=is_pending(sample))
        return {"ok": _send(settings.host_email, "[test] " + subject, body, html=html),
                "to": settings.host_email, "subject": subject}
    if kind in ("visitor_confirmed", "visitor_rescheduled", "visitor_cancelled", "visitor_reminder"):
        sample = templates.SAMPLE_BOOKING if kind == "visitor_confirmed" else templates.sample_booking_for(kind.split("_", 1)[1])
        r = templates.render_booking_visitor(sample)
        if not r:
            return {"ok": False, "error": "that visitor email is disabled"}
        subject, body = r
        if kind == "visitor_confirmed":
            html = _booking_html(sample, "visitor", templates.get_templates(), (subject, body), pending=is_pending(sample))
        else:
            from app.booking import email_html

            cta = ("Book a new time", settings.site_base_url) if kind == "visitor_cancelled" else ("Join Zoom", templates.SAMPLE_BOOKING["join_url"])
            make = {"visitor_cancelled": lambda: email_html.render_cancelled(sample, "visitor", subject, body, actions=[cta]),
                    "visitor_rescheduled": lambda: email_html.render_moved(sample, "visitor", subject, body, pending=is_pending(sample),
                                                                           actions=[cta]),
                    "visitor_reminder": lambda: email_html.render_reminder(sample, subject, body, pending=is_pending(sample), actions=[cta])}[kind]
            html = _html(make, subject, body, cta)
        return {"ok": _send(settings.host_email, "[test] " + subject, body, html=html),
                "to": settings.host_email, "subject": subject}
    if kind == "visitor_gap":
        from app import gaps

        r = gaps.render_followup(gaps.SAMPLE_PERSON, gaps.SAMPLE_ITEMS)
        if not r:
            return {"ok": False, "error": "that visitor email is disabled"}
        subject, body, cta = r
        return {"ok": _send(settings.host_email, "[test] " + subject, body, html=templates.html_wrap(subject, body, cta)),
                "to": settings.host_email, "subject": subject}
    if kind == "host":
        subject, body = render_brief(templates.SAMPLE_LEAD)
    else:
        lead = dict(templates.SAMPLE_LEAD)
        lead["status"] = "handover" if kind == "visitor_handover" else "nudge" if kind == "visitor_nudge" else "handoff"
        r = render_visitor(lead)
        if not r:
            return {"ok": False, "error": "that visitor email is disabled"}
        subject, body = r
        if kind == "visitor_nudge":  # the 24 h reminder in its HTML design; the other text emails stay text only
            return {"ok": _send(settings.host_email, "[test] " + subject, body, html=_nudge_html(lead, subject, body)),
                    "to": settings.host_email, "subject": "[test] " + subject}
        subject = "[test] " + subject
    return {"ok": _send(settings.host_email, subject, body), "to": settings.host_email, "subject": subject}
