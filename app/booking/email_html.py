"""The branded HTML version of the two in-chat booking emails (visitor confirmation, host 'New booking').

The plain-text body stays the editable template from app/templates.py and is always sent alongside; this module only
builds the HTML part, from the real booking row (app/booking/flow.py). Two states, never mixed up:

  confirmed     Zoom created the meeting (method 'scheduler' or 'meeting'): "Booking Confirmed", join link shown
  pending_zoom  the time is held in chat and the visitor still has to confirm on Zoom: "Awaiting Zoom Confirmation",
                no meeting link (there is none yet); the visitor's call to action is the prefilled Zoom link

Email-client rules followed here: table layout, inline styles (the <style> block only adds the mobile overrides),
no SVG/flex/grid/JS, PNG icons from static/email/ (built by scripts/build_email_assets.py) embedded in the message as
inline cid: parts (Gmail fetches remote images through its proxy, which never reaches a local or private host), with alt text and solid
fallback colours so the email still reads with images blocked, VML for the hero and the button in Outlook desktop.
Every dynamic value is HTML-escaped; only http(s) URLs become links.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app import templates
from app.config import settings

FONT = "Arial, Helvetica, sans-serif"
NAVY, HERO, INDIGO = "#101E50", "#07132D", "#293F91"
TEXT, TEXT2, MUTED = "#14224F", "#65769A", "#7583A4"
OUTER, PANEL, LAVENDER, BORDER = "#F4F6FA", "#F4F6FC", "#E6EBFF", "#DDE5F5"
STATUS_TEXT, STATUS_BG, STATUS_BORDER = "#233B91", "#E9EDFF", "#D8E0FF"
WIDTH = 640

_DOMAIN = re.compile(r"^(?:https?://)?((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})/?$", re.I)


# ---------------------------------------------------------------- small helpers
def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def safe_url(url: str | None) -> str:
    """The URL if it is an absolute http(s) link, else ''. Never links javascript:, data:, relative or malformed values."""
    url = (url or "").strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return url if parts.scheme in ("http", "https") and parts.netloc and not any(c in url for c in ' \t\r\n"<>') else ""


def company_link(value: str) -> str:
    """'xyz.com' or 'https://xyz.com/' becomes https://xyz.com; any other string is not linked."""
    m = _DOMAIN.match((value or "").strip())
    return f"https://{m.group(1).lower()}" if m else ""


def asset_base(booking: dict[str, Any]) -> str:
    """Where /static/email/ is reachable from the recipient's inbox: PUBLIC_BASE_URL, else the origin of the booking's
    own links (the same host the manage link points at)."""
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    for key in ("manage_url", "ics_url"):
        u = safe_url(booking.get(key))
        if u:
            p = urlsplit(u)
            return f"{p.scheme}://{p.netloc}"
    return ""


def _tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or settings.host_timezone)
    except Exception:
        return ZoneInfo("UTC")


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y")                                   # Fri, 09 Oct 2026


def fmt_time(dt: datetime) -> str:
    abbr = dt.tzname() or ""
    if not abbr or abbr[0] in "+-":                                       # zones without a letter abbreviation
        off = dt.utcoffset()
        mins = int(off.total_seconds() // 60) if off is not None else 0
        abbr = "GMT" + (f"{'+' if mins >= 0 else '-'}{abs(mins) // 60}" + (f":{abs(mins) % 60:02d}" if mins % 60 else "") if mins else "")
    return f"{dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'} {abbr}"   # 6:30 PM IST


def fmt_sent(dt: datetime) -> str:
    return f"{dt:%a, %d %b %Y}, {dt.hour % 12 or 12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


# ---------------------------------------------------------------- copy per audience and state
def _copy(audience: str, confirmed: bool, v: dict[str, str], tpl: dict[str, str]) -> dict[str, Any]:
    first, name, title = v["first_name"], v["name"] or "A visitor", v["title"]
    reminder = (settings.nudge_enabled and tpl.get("visitor_nudge_enabled", "true").strip().lower() in ("true", "1", "yes", "on"))
    hours = settings.nudge_after_hours
    if audience == "visitor" and confirmed:
        return {"eyebrow": "New booking confirmation", "heading": "Your booking is confirmed",
                "intro": [f"Hi {first},", f"Your {title} has been scheduled."], "intro2": "We’re excited to have you on board!",
                "status": "Your Zoom meeting is ready. Join with the link below when it’s time; the calendar invite is attached.",
                "preheader": f"{title} is confirmed for {v['date_visitor']}."}
    if audience == "visitor":
        return {"eyebrow": "Booking request", "heading": "Confirm your booking on Zoom",
                "intro": [f"Hi {first},", f"Your {title} time is held for you."],
                "intro2": "Confirm it on Zoom to make it final. Your details are already filled in.",
                "status": "Your time is held but not final yet. Once you confirm it on Zoom, the meeting link is sent to you.",
                "preheader": f"One last step: confirm {title} on Zoom."}
    if confirmed:
        return {"eyebrow": "New booking confirmation", "heading": "New booking confirmed",
                "intro": [f"{name} booked a {title}."], "intro2": "Zoom created the meeting and the calendar invite is attached.",
                "status": "The meeting is on Zoom. The visitor received the same details and the calendar invite.",
                "preheader": f"{name} · {title} · {v['date']}"}
    return {"eyebrow": "New booking request", "heading": "New booking request",
            "intro": [f"{name} booked a {title} in the chat."], "intro2": "The time is held while they confirm it on Zoom.",
            "status": "The visitor is still required to confirm the booking on Zoom."
                      + (f" If they haven’t within {hours} hours, they receive one automatic reminder." if reminder else ""),
            "preheader": f"{name} · {title} · awaiting Zoom confirmation"}


# ---------------------------------------------------------------- building blocks
CID = "cid"                                   # `base` value meaning: images ride inside the message (see inline_images)
ASSETS = Path(__file__).resolve().parent.parent.parent / "static" / "email"
_CID_REF = re.compile(r"cid:([a-z0-9-]+\.png)@cg")


def _src(base: str, name: str) -> str:
    return f"cid:{name}@cg" if base == CID else f"{base}/static/email/{name}"


def inline_images(html_text: str) -> list[tuple[str, bytes, str]]:
    """[(content-id, png bytes, filename)] for every cid: image the HTML references; only files in static/email/."""
    out = []
    for name in dict.fromkeys(_CID_REF.findall(html_text or "")):
        f = ASSETS / name
        if f.is_file():
            out.append((f"{name}@cg", f.read_bytes(), name))
    return out


def _img(base: str, name: str, w: int, h: int | None = None, alt: str = "", style: str = "") -> str:
    h = h or w
    return (f'<img src="{esc(_src(base, name))}" width="{w}" height="{h}" alt="{esc(alt)}" '
            f'style="display:block;width:{w}px;height:{h}px;border:0;outline:none;text-decoration:none;{style}">')


def _label(text: str) -> str:
    return (f'<div style="font-family:{FONT};font-size:11px;line-height:16px;font-weight:700;letter-spacing:1.6px;'
            f'text-transform:uppercase;color:{TEXT2}">{esc(text)}</div>')


def _link(url: str, text: str, color: str = STATUS_TEXT, weight: int = 700) -> str:
    return f'<a href="{esc(url)}" style="color:{color};font-weight:{weight};text-decoration:none">{esc(text)}</a>'


def _divider(top: int = 22, bottom: int = 22) -> str:
    return (f'<tr><td style="padding:{top}px 0 {bottom}px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td height="1" style="height:1px;line-height:1px;font-size:1px;background:{BORDER}">&nbsp;</td></tr></table></td></tr>')


def _person_row(base: str, icon: str, alt: str, label: str, lines: list[str]) -> str:
    """Icon in a lavender circle, then a label and one or more value lines (already-escaped HTML)."""
    body = "".join(lines)
    return (f'<tr><td><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td valign="top" width="36" style="width:36px;padding:2px 14px 0 0">{_img(base, icon, 36, alt=alt, style="background:#E6EBFF;border-radius:18px")}</td>'
            f'<td valign="top">{_label(label)}{body}</td></tr></table></td></tr>')


def _column(base: str, icon: str, alt: str, label: str, value: str, extra: str, cls: str, first: bool) -> str:
    border = "" if first else f"border-left:1px solid {BORDER};"
    pad = "padding:0 14px 0 0" if first else "padding:0 14px 0 18px"
    return (f'<td class="{cls}" valign="top" width="33%" style="width:33%;{border}{pad}">'
            f'{_img(base, icon, 36, alt=alt, style="background:#E6EBFF;border-radius:18px")}<div style="height:12px;line-height:12px;font-size:12px">&nbsp;</div>{_label(label)}'
            f'<div style="font-family:{FONT};font-size:15px;line-height:22px;font-weight:700;color:{TEXT};padding-top:4px">{value}</div>'
            f'{extra}</td>')


def _button(url: str, text: str, base: str) -> str:
    """Table button with a real link; VML roundrect keeps the shape in Outlook desktop."""
    u, t = esc(url), esc(text)
    return (f'<table class="btnt" role="presentation" align="center" cellpadding="0" cellspacing="0" border="0" style="margin:0 auto"><tr><td align="center">'
            f'<!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{u}" '
            f'style="height:50px;v-text-anchor:middle;width:290px;" arcsize="16%" stroke="f" fillcolor="{NAVY}"><w:anchorlock/>'
            f'<center style="color:#ffffff;font-family:{FONT};font-size:15px;font-weight:bold;">{t}</center></v:roundrect><![endif]-->'
            f'<!--[if !mso]><!-->'
            f'<a class="btn" href="{u}" style="display:inline-block;width:290px;max-width:100%;box-sizing:border-box;background:{NAVY};color:#ffffff;'
            f'font-family:{FONT};font-size:15px;line-height:50px;font-weight:700;text-align:center;text-decoration:none;border-radius:8px;'
            f'box-shadow:0 6px 16px -8px rgba(16,30,80,.55)">'
            f'<img src="{esc(_src(base, "ic-external.png"))}" width="14" height="14" alt="" '
            f'style="display:inline-block;width:14px;height:14px;border:0;vertical-align:-2px;margin-right:8px">{t}</a>'
            f'<!--<![endif]--></td></tr></table>')


def _hero(base: str, brand: str, copy: dict[str, Any]) -> str:
    bg = _src(base, "hero.png")
    intro = "".join(f'<p style="margin:0 0 {10 if i < len(copy["intro"]) - 1 else 0}px;font-family:{FONT};font-size:17px;line-height:28px;color:#FFFFFF">{esc(t)}</p>'
                    for i, t in enumerate(copy["intro"]))
    content = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td class="stack" valign="middle" style="font-family:{FONT};font-size:19px;line-height:24px;font-weight:700;color:#FFFFFF">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="middle" style="padding-right:10px">{_img(base, "star-white.png", 22, alt="")}</td>'
        f'<td valign="middle" style="font-family:{FONT};font-size:19px;line-height:24px;font-weight:700;color:#FFFFFF">{esc(brand)}</td></tr></table></td>'
        f'<td class="stack tag" align="right" valign="middle" style="font-family:{FONT};font-size:10px;line-height:16px;font-weight:700;'
        f'letter-spacing:2px;text-transform:uppercase;color:#9FB0DA;white-space:nowrap">Strategy · Growth · Impact</td></tr></table>'
        f'<div style="font-family:{FONT};font-size:12px;line-height:18px;font-weight:700;letter-spacing:3px;text-transform:uppercase;'
        f'color:#C7D4F5;padding-top:34px">{esc(copy["eyebrow"])}</div>'
        f'<h1 class="h1" style="margin:14px 0 20px;max-width:550px;font-family:{FONT};font-size:46px;line-height:50px;font-weight:700;'
        f'letter-spacing:-0.5px;color:#FFFFFF">{esc(copy["heading"])}</h1>'
        f'<div style="max-width:500px">{intro}'
        f'<p style="margin:12px 0 0;font-family:{FONT};font-size:16px;line-height:27px;color:#D3DCF3">{esc(copy["intro2"])}</p></div>')
    return (
        f'<!--[if mso]><v:rect xmlns:v="urn:schemas-microsoft-com:vml" fill="true" stroke="false" style="width:{WIDTH - 32}px;">'
        f'<v:fill type="frame" src="{esc(bg)}" color="{HERO}"/><v:textbox inset="0,0,0,0" style="mso-fit-shape-to-text:true"><![endif]-->'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate"><tr>'
        f'<td class="hero" background="{esc(bg)}" bgcolor="{HERO}" valign="top" style="background-color:{HERO};'
        f'background-image:url(\'{esc(bg)}\'),linear-gradient(115deg,{HERO} 0%,#111F4D 55%,{INDIGO} 100%);background-size:cover;'
        f'background-position:right bottom;background-repeat:no-repeat;border-radius:10px;padding:40px 44px 46px">{content}</td></tr></table>'
        f'<!--[if mso]></v:textbox></v:rect><![endif]-->')


# ---------------------------------------------------------------- the email
def render(booking: dict[str, Any], audience: str, tpl: dict[str, str] | None = None, now: datetime | None = None, *,
           brief: str = "", notice: str = "", cta_ok: bool = True, images: str = "inline") -> str:
    """HTML for audience 'visitor' or 'host'. `booking` is the dict stored by app/booking/flow.py (or SAMPLE_BOOKING).
    Host extras: `brief` is the pre-call brief as text (app/precall.text), `notice` a late update shown above the status
    ("the visitor has already cancelled"), `cta_ok=False` drops the button (nothing left to view or join)."""
    tpl = tpl or templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    confirmed = booking.get("status") == "confirmed"
    copy = _copy(audience, confirmed, v, tpl)
    base = CID if images == "inline" else asset_base(booking)   # "url": a browser preview against the running app
    brand = tpl.get("brand_default") or templates.DEFAULTS["brand_default"]
    tz = _tz(booking.get("visitor_tz") if audience == "visitor" else settings.host_timezone)
    start = booking.get("start_utc")
    start = start.astimezone(tz) if isinstance(start, datetime) else None
    sent = (now or datetime.now(timezone.utc)).astimezone(tz)
    recipient = booking.get("email") if audience == "visitor" else settings.host_email

    # status pill
    pill_text = "Booking Confirmed" if confirmed else "Awaiting Zoom Confirmation"
    pill = (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate"><tr>'
            f'<td style="background:{STATUS_BG};border:1px solid {STATUS_BORDER};border-radius:999px;padding:9px 18px 9px 14px">'
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td valign="middle" style="padding-right:8px">{_img(base, "ic-status.png", 16, alt="")}</td>'
            f'<td valign="middle" style="font-family:{FONT};font-size:13px;line-height:18px;font-weight:700;color:{STATUS_TEXT};white-space:nowrap">'
            f'{esc(pill_text)}</td></tr></table></td></tr></table>')

    # three columns: date, time, platform
    method = booking.get("method") or ""
    links = " ".join(str(booking.get(k) or "") for k in ("join_url", "handoff_url"))
    platform = "Zoom" if method in ("scheduler", "meeting", "handoff", "browser") or "zoom.us" in links else "Online"
    join = safe_url(booking.get("join_url")) if confirmed else ""
    confirm_url = safe_url(booking.get("handoff_url")) if not confirmed else ""
    plat_extra = ""
    if join:
        plat_extra = f'<div style="font-family:{FONT};font-size:14px;line-height:20px;padding-top:4px">{_link(join, "Join meeting →")}</div>'
    if confirmed and booking.get("meeting_id"):
        mid = f"ID {booking['meeting_id']}" + (f" · Passcode {booking['passcode']}" if booking.get("passcode") else "")
        plat_extra += f'<div style="font-family:{FONT};font-size:12px;line-height:18px;color:{MUTED};padding-top:2px">{esc(mid)}</div>'
    duration = booking.get("duration_min")
    dur = f'<div style="font-family:{FONT};font-size:13px;line-height:19px;color:{TEXT2}">({esc(duration)} minutes)</div>' if duration else ""
    cols = ""
    if start:
        cols = (f'<tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
                + _column(base, "ic-date.png", "", "Date", esc(fmt_date(start)), "", "col", True)
                + _column(base, "ic-time.png", "", "Time", esc(fmt_time(start)), dur, "col col-b", False)
                + _column(base, "ic-platform.png", "", "Platform", esc(platform), plat_extra, "col col-b", False)
                + "</tr></table></td></tr>" + _divider(26, 24))

    # attendee, company
    email = (booking.get("email") or "").strip()
    email_html = (_link(f"mailto:{email}", email, STATUS_TEXT, 400) if _email_ok(email) else esc(email))
    notes = (booking.get("notes") or booking.get("reason") or "").strip() if audience == "host" else ""
    attendee = _person_row(base, "ic-user.png", "", "Attendee", [
        f'<div style="font-family:{FONT};font-size:16px;line-height:24px;font-weight:700;color:{TEXT};padding-top:4px">{esc(booking.get("name") or "")}</div>',
        f'<div style="font-family:{FONT};font-size:15px;line-height:22px;color:{TEXT2}">{email_html}</div>',
        (f'<div style="font-family:{FONT};font-size:14px;line-height:21px;color:{TEXT2};padding-top:6px">Notes: {esc(notes)}</div>' if notes else "")])
    company = (booking.get("company") or "").strip() or (booking.get("company_line") or "").strip()
    company_row = ""
    if company:
        href = company_link(company)
        shown = _link(href, company, TEXT, 700) if href else esc(company)
        detail = (booking.get("company_line") or "").strip() if audience == "host" else ""
        company_row = _divider() + _person_row(base, "ic-company.png", "", "Company", [
            f'<div style="font-family:{FONT};font-size:16px;line-height:24px;font-weight:700;color:{TEXT};padding-top:4px">{shown}</div>',
            (f'<div style="font-family:{FONT};font-size:14px;line-height:21px;color:{TEXT2}">{esc(detail)}</div>' if detail and detail != company else "")])

    guests = [g for g in (booking.get("attendees") or []) if isinstance(g, dict) and (g.get("email") or g.get("name"))]
    guests_row = ""
    if guests:
        lines = []
        for g in guests:
            em = (g.get("email") or "").strip()
            mail = _link(f"mailto:{em}", em, STATUS_TEXT, 400) if _email_ok(em) else esc(em)
            nm = esc((g.get("name") or "").strip())
            lines.append(f'<div style="font-family:{FONT};font-size:15px;line-height:22px;color:{TEXT};padding-top:4px">'
                         + (f'<b>{nm}</b>' + (" · " if em else "") if nm else "") + f'<span style="color:{TEXT2}">{mail}</span></div>')
        guests_row = _divider() + _person_row(base, "ic-user.png", "", "Guests", lines)
    brief_row = (_divider() + f'<tr><td>{_brief_html(brief)}</td></tr>') if brief and audience == "host" else ""

    # call to action: the booking page; for a visitor who still has to confirm, the prefilled Zoom link
    manage = safe_url(booking.get("manage_url"))
    if audience == "visitor" and not confirmed and confirm_url:
        cta = ("Confirm on Zoom", confirm_url)
    elif manage:
        cta = ("View booking details", manage)
    else:
        cta = None
    cta_html = f'<tr><td style="padding-top:30px">{_button(cta[1], cta[0], base)}</td></tr>' if cta and cta_ok else ""

    card = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;background:#FFFFFF;border:1px solid #E1E7F5;border-radius:10px">'
            f'<tr><td class="card" style="padding:28px 28px 30px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td class="evi" valign="top" width="56" style="width:56px;padding-right:18px">{_img(base, "ic-event.png", 56, style="background:#E6EBFF;border-radius:12px")}</td>'
            f'<td valign="middle">{_label("Event details")}'
            f'<div class="evt" style="font-family:{FONT};font-size:24px;line-height:33px;font-weight:700;color:{TEXT};padding-top:4px;max-width:600px">'
            f'{esc(v["title"])}</div></td></tr></table></td></tr>'
            + _divider(24, 24) + cols + attendee + company_row + guests_row + brief_row + cta_html +
            '</table></td></tr></table>')

    panel = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;background:{PANEL};border-radius:12px">'
             f'<tr><td class="panel" style="padding:18px 16px 16px">{_notice_html(notice)}{pill}'
             f'<p style="margin:12px 0 22px;max-width:520px;font-family:{FONT};font-size:15px;line-height:24px;color:{TEXT2}">{esc(copy["status"])}</p>'
             f'{card}</td></tr></table>')

    sender = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
              f'<td class="stack" valign="middle"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
              f'<td valign="middle" width="44" style="width:44px;padding-right:14px">{_img(base, "brand-tile.png", 44, alt=brand[:1], style=f"background:{NAVY};border-radius:11px;color:#FFFFFF;font-family:{FONT};font-size:18px;font-weight:700;line-height:44px;text-align:center")}</td>'
              f'<td valign="middle"><div style="font-family:{FONT};font-size:17px;line-height:22px;font-weight:700;color:{TEXT}">{esc(brand)}</div>'
              f'<div style="font-family:{FONT};font-size:14px;line-height:20px;color:{TEXT2}">{esc(settings.email_from)}</div>'
              f'<div style="font-family:{FONT};font-size:13px;line-height:19px;color:{TEXT2}">to {esc(recipient)}</div></td></tr></table></td>'
              f'<td class="stack sent" align="right" valign="top" style="font-family:{FONT};font-size:13px;line-height:20px;color:{TEXT2};white-space:nowrap;padding-top:2px">'
              f'{esc(fmt_sent(sent))}</td></tr></table>')

    footer_note = ("This email was sent by Champions Group. If you have any questions or need to reschedule, please reach out to your host "
                   "by replying to this email." if audience == "visitor"
                   else "This email was sent by the Champions Group website assistant. Reply to this email to reach the visitor directly.")
    footer = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
              f'<tr><td height="1" style="height:1px;line-height:1px;font-size:1px;background:{BORDER}">&nbsp;</td></tr>'
              f'<tr><td style="padding:22px 0 14px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
              f'<td class="stack" valign="middle"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
              f'<td valign="middle" style="padding-right:9px">{_img(base, "star-navy.png", 20, alt="")}</td>'
              f'<td valign="middle" style="font-family:{FONT};font-size:16px;line-height:22px;font-weight:700;color:{TEXT}">{esc(brand)}</td></tr></table></td>'
              f'<td class="stack tag" align="right" valign="middle" style="font-family:{FONT};font-size:10px;line-height:16px;font-weight:700;letter-spacing:1.5px;'
              f'text-transform:uppercase;color:{MUTED};white-space:nowrap">Better conversations. Bigger outcomes.</td></tr></table></td></tr>'
              f'<tr><td style="font-family:{FONT};font-size:12px;line-height:19px;color:{MUTED};max-width:600px">{esc(footer_note)}</td></tr></table>')

    return f"""<!doctype html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{esc(copy["heading"])}</title>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
<style>
  body {{ margin:0; padding:0; width:100% !important; -webkit-text-size-adjust:100%; -ms-text-size-adjust:100% }}
  table {{ border-collapse:collapse; mso-table-lspace:0pt; mso-table-rspace:0pt }}
  img {{ -ms-interpolation-mode:bicubic }}
  a[x-apple-data-detectors] {{ color:inherit !important; text-decoration:none !important }}
  @media only screen and (max-width:620px) {{
    .outer {{ padding:12px 8px !important }}
    .px {{ padding-left:16px !important; padding-right:16px !important }}
    .hpx {{ padding-left:8px !important; padding-right:8px !important }}
    .hero {{ padding:28px 22px 30px !important }}
    .h1 {{ font-size:31px !important; line-height:36px !important }}
    .panel {{ padding:14px 10px 12px !important }}
    .card {{ padding:20px 16px 22px !important }}
    .evt {{ font-size:20px !important; line-height:28px !important }}
    .evi {{ padding-right:12px !important }}
    .stack {{ display:block !important; width:100% !important; text-align:left !important }}
    .tag {{ padding-top:10px !important; white-space:normal !important }}
    .sent {{ padding-top:10px !important }}
    .col {{ display:block !important; width:100% !important; padding:0 !important }}
    .col-b {{ border-left:0 !important; border-top:1px solid {BORDER} !important; padding-top:16px !important; margin-top:16px !important }}
    .btnt {{ width:100% !important }}
    .btn {{ display:block !important; width:100% !important }}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:{OUTER}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;mso-hide:all">{esc(copy["preheader"])}&#8204;&nbsp;&#8204;&nbsp;&#8204;&nbsp;&#8204;&nbsp;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{OUTER}" style="background:{OUTER}">
<tr><td class="outer" align="center" style="padding:25px 12px">
<!--[if mso]><table role="presentation" width="{WIDTH}" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;max-width:{WIDTH}px;width:100%;background:#FFFFFF;border:1px solid #E6EAF3;border-radius:12px">
<tr><td class="px" style="padding:22px 24px 20px">{sender}</td></tr>
<tr><td class="hpx" style="padding:0 16px">{_hero(base, brand, copy)}</td></tr>
<tr><td class="px" style="padding:28px 24px 0">{panel}</td></tr>
<tr><td class="px" style="padding:28px 24px 26px">{footer}</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>"""


def _notice_html(notice: str) -> str:
    if not notice:
        return ""
    return (f'<div style="margin:0 0 14px;padding:10px 14px;border-radius:8px;background:#FFF4E5;border:1px solid #F5D9A8;'
            f'font-family:{FONT};font-size:14px;line-height:21px;font-weight:700;color:#7A4B00">{esc(notice)}</div>')


def _brief_html(text: str) -> str:
    """The pre-call brief (app/precall.text): UPPERCASE lines are headings, 'Key:  value' lines a fact table, '• ' bullets."""
    out, rows, items = [], [], []

    def flush():
        if rows:
            out.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 8px">' + "".join(rows) + "</table>")
            rows.clear()
        if items:
            out.append(f'<ul style="margin:2px 0 8px;padding:0 0 0 18px;font-family:{FONT};font-size:14px;line-height:21px;color:{TEXT}">'
                       + "".join(f'<li style="margin:0 0 3px">{t}</li>' for t in items) + "</ul>")
            items.clear()

    for ln in (text or "").splitlines():
        t = ln.rstrip()
        if not t.strip():
            flush()
            continue
        m = re.match(r"^([A-Za-z][A-Za-z ]{0,14}):\s+(.*)$", t)
        if items and not t.lstrip().startswith("• "):
            flush()
        if t.strip().isupper() and len(t.strip()) <= 40:
            flush()
            out.append(f'<div style="padding:{8 if out else 0}px 0 6px">{_label(t.strip())}</div>')
        elif m:
            rows.append(f'<tr><td valign="top" style="font-family:{FONT};font-size:13px;line-height:20px;color:{TEXT2};padding:2px 14px 2px 0;white-space:nowrap">{esc(m.group(1))}</td>'
                        f'<td valign="top" style="font-family:{FONT};font-size:14px;line-height:20px;color:{TEXT};padding:2px 0">{esc(m.group(2))}</td></tr>')
        elif t.lstrip().startswith("• "):
            if rows:
                flush()
            items.append(esc(t.lstrip()[2:]))
        else:
            flush()
            out.append(f'<p style="margin:0 0 8px;font-family:{FONT};font-size:14px;line-height:21px;color:{TEXT}">{esc(t)}</p>')
    flush()
    return "".join(out)


def _email_ok(email: str) -> bool:
    """A plausible single address (what the booking form already validated); anything else is shown as text, not linked."""
    return bool(re.fullmatch(r"[^\s@<>\"']+@[^\s@<>\"']+\.[A-Za-z]{2,}", email or ""))
