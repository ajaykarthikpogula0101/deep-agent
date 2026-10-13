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


def attendee_notice(booking: dict[str, Any], guest: dict[str, str], kind: str, tpl: dict[str, str] | None = None) -> tuple[str, str, tuple[str, str] | None]:
    """(subject, body, call-to-action) for one extra guest: "booked" (invited), "moved", "cancelled" or "reminder".
    Written to the guest, never as if they had booked themselves."""
    tpl = tpl or templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    first = (guest.get("name") or "").strip().split(" ")[0] or "there"
    booker = v["name"] or "A colleague"
    pending = booking.get("status") == "pending_zoom" or booking.get("method") == "handoff"
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
    for g in guests:
        subject, body, cta = attendee_notice(booking, g, kind, tpl)
        mailer.enqueue(g["email"], subject, body, html=templates.html_wrap(subject, body, cta), attachments=attachments,
                       reply_to=settings.host_email, kind=f"attendee_{kind}", ref=booking.get("id"))
    return len(guests)


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
        cta = ("Join Zoom", booking["join_url"]) if booking.get("join_url") else (("Confirm on Zoom", booking["handoff_url"]) if booking.get("handoff_url") else None)
        mailer.enqueue(booking["email"], v[0], v[1], html=templates.html_wrap(v[0], v[1], cta), attachments=att,
                       reply_to=settings.host_email, kind="booking_visitor", ref=booking.get("id"))
    s, b = templates.render_booking_host(booking, tpl)
    cta_h = ("Join Zoom", booking["join_url"]) if booking.get("join_url") else None
    mailer.enqueue(settings.host_email, s, b, html=templates.html_wrap(s, b, cta_h, audience="host"), attachments=att, reply_to=booking.get("email"),
                   kind="booking_host", ref=booking.get("id"))
    send_attendee_emails(booking, "booked", mailer, att)


def send_reschedule_emails(booking: dict[str, Any], mailer=None) -> None:
    """Both sides hear about the new time; the visitor copy carries a fresh .ics invite."""
    from app import mailer as m
    from app.booking import ics

    mailer = mailer or m.default
    tpl = templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    was = booking.get("old_label_visitor") or "the earlier time"
    pending = booking.get("status") == "pending_zoom" or booking.get("method") == "handoff"
    subject = f"Moved: {v['title']} now on {v['date_visitor']}"
    att = [("invite.ics", ics.build(booking, tpl.get("host_name") or "Deep"), "text/calendar")]
    cta = ("Confirm on Zoom", booking["handoff_url"]) if pending and booking.get("handoff_url") else (("Join Zoom", booking["join_url"]) if booking.get("join_url") else None)
    # the visitor copy is the editable "visitor_rescheduled" template (Console -> Emails); the link rides as `link` for the next step
    r = templates.render_booking_visitor(dict(booking, status="rescheduled", booking_status="pending_zoom" if pending else "confirmed",
                                              old_label_visitor=was, old_label_host=booking.get("old_label_host") or ""), tpl)
    if r and booking.get("email"):
        mailer.enqueue(booking["email"], r[0], r[1], html=templates.html_wrap(r[0], r[1], cta), attachments=att,
                       reply_to=settings.host_email, kind="reschedule_visitor", ref=booking.get("id"))
    body_h = (f"The visitor moved their call.\n\nName:   {v['name']}\nEmail:  {v['email']}\nCall:   {v['title']}\nWas:    {was}\nNow:    {v['date']}\n"
              + ("Status: held, waiting for the visitor to confirm on Zoom\n" if pending else "Status: rescheduled on Zoom Scheduler\n"))
    mailer.enqueue(settings.host_email, f"[{v['brand']}] Moved: {v['name']} · {v['title']} · {v['date']}", body_h,
                   html=templates.html_wrap(subject, body_h, cta if not pending else None, audience="host"), attachments=att, reply_to=booking.get("email"),
                   kind="reschedule_host", ref=booking.get("id"))
    send_attendee_emails(dict(booking, old_label_visitor=was), "moved", mailer, att)


def send_cancel_emails(booking: dict[str, Any], mailer=None) -> None:
    from app import mailer as m

    mailer = mailer or m.default
    tpl = templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    subject = f"Cancelled: {v['title']} on {v['date_visitor']}"
    body_h = (f"Cancelled by the visitor.\n\nName:   {v['name']}\nEmail:  {v['email']}\nCall:   {v['title']}\nWas:    {v['date']}\n"
              + (f"Note:   {booking['zoom_note']}\n" if booking.get("zoom_note") else ""))
    r = templates.render_booking_visitor(dict(booking, status="cancelled", booking_status="cancelled"), tpl)  # editable "visitor_cancelled"
    if r and booking.get("email"):
        mailer.enqueue(booking["email"], r[0], r[1], html=templates.html_wrap(r[0], r[1], ("Book a new time", settings.site_base_url)),
                       reply_to=settings.host_email, kind="cancel_visitor", ref=booking.get("id"))
    mailer.enqueue(settings.host_email, f"[{v['brand']}] {subject} · {v['name']}", body_h, html=templates.html_wrap(subject, body_h, None, audience="host"),
                   reply_to=booking.get("email"), kind="cancel_host", ref=booking.get("id"))
    send_attendee_emails(booking, "cancelled", mailer)


def send_reminder_email(booking: dict[str, Any], mailer=None) -> bool:
    """The day-before reminder (app/reminders.py): the editable "visitor_reminder" template with the join or confirm link.
    Returns False when the template is disabled or the booking has no email."""
    from app import mailer as m

    mailer = mailer or m.default
    tpl = templates.get_templates()
    pending = booking.get("status") == "pending_zoom" or booking.get("method") == "handoff"
    r = templates.render_booking_visitor(dict(booking, status="reminder", booking_status="pending_zoom" if pending else "confirmed"), tpl)
    if not r or not booking.get("email"):
        return False
    cta = ("Confirm on Zoom", booking["handoff_url"]) if pending and booking.get("handoff_url") else (("Join Zoom", booking["join_url"]) if booking.get("join_url") else None)
    mailer.enqueue(booking["email"], r[0], r[1], html=templates.html_wrap(r[0], r[1], cta), reply_to=settings.host_email,
                   kind="reminder_visitor", ref=booking.get("id"))
    send_attendee_emails(booking, "reminder", mailer)
    return True


def send_test(kind: str) -> dict:
    """Console → Emails → 'Send test': the sample lead rendered with the current templates, to the host inbox."""
    if kind == "host_booking":
        subject, body = templates.render_booking_host(templates.SAMPLE_BOOKING)
        return {"ok": _send(settings.host_email, "[test] " + subject, body, html=templates.html_wrap(subject, body, ("Join Zoom", templates.SAMPLE_BOOKING["join_url"]), audience="host")),
                "to": settings.host_email, "subject": subject}
    if kind in ("visitor_confirmed", "visitor_rescheduled", "visitor_cancelled", "visitor_reminder"):
        sample = templates.SAMPLE_BOOKING if kind == "visitor_confirmed" else templates.sample_booking_for(kind.split("_", 1)[1])
        r = templates.render_booking_visitor(sample)
        if not r:
            return {"ok": False, "error": "that visitor email is disabled"}
        subject, body = r
        cta = ("Book a new time", settings.site_base_url) if kind == "visitor_cancelled" else ("Join Zoom", templates.SAMPLE_BOOKING["join_url"])
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
        subject = "[test] " + subject
    return {"ok": _send(settings.host_email, subject, body), "to": settings.host_email, "subject": subject}
