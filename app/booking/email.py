"""Outbound email over SMTP: the host brief and the visitor confirmation, both rendered from the editable
templates in app/templates.py. If SMTP is not configured the message is logged and the lead row still exists."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any

from app import templates
from app.config import settings

log = logging.getLogger("booking.email")


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
    return _send(lead["email"], subject, body, reply_to=settings.host_email)


def send_booking_emails(booking: dict[str, Any], mailer=None) -> None:
    """Visitor confirmation + host 'New booking', both with the .ics invite, queued on the background mailer."""
    from app import mailer as m
    from app.booking import ics

    mailer = mailer or m.default
    tpl = templates.get_templates()
    invite = ics.build(booking, tpl.get("host_name") or "Deep")
    att = [("invite.ics", invite, "text/calendar")]
    v = templates.render_booking_visitor(booking, tpl)
    if v and booking.get("email"):
        mailer.enqueue(booking["email"], v[0], v[1], html=_booking_html(booking, "visitor", tpl, v), attachments=att,
                       reply_to=settings.host_email, kind="booking_visitor", ref=booking.get("id"))
    s, b = templates.render_booking_host(booking, tpl)
    mailer.enqueue(settings.host_email, s, b, html=_booking_html(booking, "host", tpl, (s, b)), attachments=att, reply_to=booking.get("email"),
                   kind="booking_host", ref=booking.get("id"))


def _booking_html(booking: dict[str, Any], audience: str, tpl: dict[str, str], text: tuple[str, str]) -> str:
    """The branded booking email (app/booking/email_html.py); the simple card if it ever fails, so the mail still goes out."""
    from app.booking import email_html

    try:
        return email_html.render(booking, audience, tpl)
    except Exception as e:
        log.error("booking email html failed, sending the simple version: %s", e)
        return templates.html_wrap(text[0], text[1], None)


def send_cancel_emails(booking: dict[str, Any], mailer=None) -> None:
    from app import mailer as m

    mailer = mailer or m.default
    v = templates.build_vars(templates.booking_to_lead(booking))
    subject = f"Cancelled: {v['title']} on {v['date_visitor']}"
    body_v = (f"Hi {v['first_name']},\n\nYour {v['title']} with {v['host_name']} on {v['date_visitor']} has been cancelled.\n\n"
              f"To pick a new time, open the chat on {v['site']} and say 'book a call', or use {settings.zoom_booking_base}.\n\n{v['host_name']}\n{v['site']}\n")
    body_h = (f"Cancelled by the visitor.\n\nName:   {v['name']}\nEmail:  {v['email']}\nCall:   {v['title']}\nWas:    {v['date']}\n"
              + (f"Note:   {booking['zoom_note']}\n" if booking.get("zoom_note") else ""))
    if booking.get("email"):
        mailer.enqueue(booking["email"], subject, body_v, html=templates.html_wrap(subject, body_v, None), reply_to=settings.host_email,
                       kind="cancel_visitor", ref=booking.get("id"))
    mailer.enqueue(settings.host_email, f"[{v['brand']}] {subject} · {v['name']}", body_h, html=templates.html_wrap(subject, body_h, None),
                   reply_to=booking.get("email"), kind="cancel_host", ref=booking.get("id"))


def send_test(kind: str) -> dict:
    """Console → Emails → 'Send test': the sample lead rendered with the current templates, to the host inbox."""
    if kind == "host_booking":
        subject, body = templates.render_booking_host(templates.SAMPLE_BOOKING)
        html = _booking_html(templates.SAMPLE_BOOKING, "host", templates.get_templates(), (subject, body))
        return {"ok": _send(settings.host_email, "[test] " + subject, body, html=html),
                "to": settings.host_email, "subject": subject}
    if kind == "visitor_confirmed":
        r = templates.render_booking_visitor(templates.SAMPLE_BOOKING)
        if not r:
            return {"ok": False, "error": "that visitor email is disabled"}
        subject, body = r
        html = _booking_html(templates.SAMPLE_BOOKING, "visitor", templates.get_templates(), (subject, body))
        return {"ok": _send(settings.host_email, "[test] " + subject, body, html=html),
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
        subject = "[test] " + subject
    return {"ok": _send(settings.host_email, subject, body), "to": settings.host_email, "subject": subject}
