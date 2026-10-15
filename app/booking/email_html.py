"""The HTML part of every booking-lifecycle email, built from one design system ("Ledger").

The plain-text body (the editable template from app/templates.py, or the fixed text of the host and guest notes) is
always sent alongside and is never changed here; this module only builds the HTML part, from the real booking row
(app/booking/flow.py) and that same text. The state comes from the booking and from the send function, never the other
way round: the caller passes `pending` (status 'pending_zoom' or method 'handoff', app/booking/email.is_pending) and
the buttons it already computed.

  #1 visitor / #2 host confirmation   render()            confirmed, or pending_zoom (held until confirmed on Zoom)
  #3 #4 cancelled                     render_cancelled()
  #5 #6 rescheduled                   render_moved()      before-and-after block
  #7 day-before reminder              render_reminder()   "Tomorrow" / "Today" / "Upcoming"
  #8 the host's day-before brief      render_host_brief() the pre-call brief as its own section
  #9 unconfirmed-hold reminder        render_nudge()
  #10-13 extra guests                 render_guest()      invited / moved / cancelled / reminder

The system: one 600px column on a soft canvas, a small header (monogram tile, brand, an eyebrow label), one white
card with status pills, the heading, a short lead, the event card (a live-text date tile whose top strip carries the
state colour, then key/value rows), notes and bulletproof buttons, and a quiet footer. No images at all: every element
is live text or a coloured cell, so blocked images change nothing. Colours are inline (light); a second <style> block
re-colours by class for clients with a dark mode (prefers-color-scheme, and Outlook.com's data-og* attributes);
clients that invert colours on their own get a design that survives it (hairline card border, mid-tone violet button,
light tints with dark text).

The lifecycle emails (#3-#13) keep their wording from the text part: its paragraphs are the lead and the notes, its
"Label:   value" lines the event card's rows (the call, its time and the Zoom line become the tile, the before-and-after
block and the Join row), its sign-off the sign-off. So a wording edit in Console -> Emails shows in both parts.

Email-client rules followed here: table layout, inline styles (the <style> blocks only add mobile and dark-mode
overrides), no SVG/flex/grid/JS/web fonts (system font stack), VML buttons for Outlook desktop. Every dynamic value is
HTML-escaped; only safe_url()/company_link() output (and mailto: for a valid address) becomes an href.

The image delivery mechanism (EMAIL_ASSETS_URL hosted PNGs, inline cid: parts, or URLs for a browser preview) stays
for any future email that references images in static/email/; no current email does.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from app import templates
from app.config import settings

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
    for key in ("host_url", "manage_url", "ics_url"):
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


def _email_ok(email: str) -> bool:
    """A plausible single address (what the booking form already validated); anything else is shown as text, not linked."""
    return bool(re.fullmatch(r"[^\s@<>\"']+@[^\s@<>\"']+\.[A-Za-z]{2,}", email or ""))


# ---------------------------------------------------------------- copy per audience and state (#1 and #2)
def _copy(audience: str, confirmed: bool, v: dict[str, str], tpl: dict[str, str]) -> dict[str, Any]:
    first, name, title = v["first_name"], v["name"] or "A visitor", v["title"]
    reminder = (settings.nudge_enabled and tpl.get("visitor_nudge_enabled", "true").strip().lower() in ("true", "1", "yes", "on"))
    hours = settings.nudge_after_hours
    host = v.get("host_name") or "Deep"
    if audience == "visitor" and confirmed:
        return {"eyebrow": "", "heading": f"Your call with {host} is confirmed",
                "intro": [f"Hi {first},", f"Your {title} is booked. The details are below, and a calendar invite is attached."],
                "intro2": "",
                "status": ("Join from the button below at the scheduled time. Reply to this email if anything changes."
                           if v.get("join_url") else
                           "Zoom sends the meeting link in its own invitation; join from there at the scheduled time."),
                "preheader": f"{title} on {v['date_visitor']}. Join details and calendar invite inside."}
    if audience == "visitor":
        return {"eyebrow": "", "heading": "Confirm your time on Zoom",
                "intro": [f"Hi {first},", f"We’re holding this time for your {title}. Confirm it on Zoom to finish booking; "
                                          "your details are already filled in."],
                "intro2": "",
                "status": "Your meeting link is sent as soon as you confirm.",
                "preheader": f"One step left: confirm {title} on Zoom."}
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


FOOTER_NOTE = {
    "visitor": "Questions about your booking? Reply to this email and Deep’s team will get back to you.",
    "host": "This email was sent by the Champions Group website assistant. Reply to this email to reach the visitor directly.",
}


# ---------------------------------------------------------------- image delivery (static/email/*.png)
CID = "cid"                                   # `base` value meaning: images ride inside the message (see inline_images)
ASSETS = Path(__file__).resolve().parent.parent.parent / "static" / "email"
_CID_REF = re.compile(r"cid:([a-z0-9-]+\.png)@cg")


def image_base(booking: dict[str, Any], images: str = "hosted") -> str:
    """Where an email's PNGs come from. 'url': a browser preview against the running app; otherwise a real email: the
    public https folder (EMAIL_ASSETS_URL), else inline parts (CID)."""
    if images == "url":
        return asset_base(booking) + "/static/email"
    hosted = safe_url(settings.email_assets_url)
    return hosted if hosted.startswith("https://") and images != "inline" else CID


def _src(base: str, name: str) -> str:
    """`base` is CID or a folder URL that holds the PNGs."""
    return f"cid:{name}@cg" if base == CID else f"{base.rstrip('/')}/{name}"


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


# ================================================================ Ledger: the design system
# ---------------------------------------------------------------- tokens
# Champions Group brand: white surfaces, ink text, Champions Orange for the one action and the wordmark; greys stay
# neutral. A state is a short coloured word above the heading, never a badge.
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
CANVAS, SURFACE, SUBTLE = "#F5F5F5", "#FFFFFF", "#FAFAFA"
INK, BODY, MUTE = "#1A1A1A", "#3F3F46", "#6B6B6B"
LINE, LINE_STRONG = "#E5E7EB", "#D4D4D8"
ACCENT, ACCENT_TEXT = "#F26722", "#C2410C"          # Champions Orange (fills, white text) / its darker shade for links
MAX_W = 600

# state -> (class, unused, text colour, unused, unused, unused): the shape older callers index into
STATES: dict[str, tuple[str, str, str, str, str, str]] = {
    "ok":   ("st-ok",   "", "#15803D", "", "", ""),
    "wait": ("st-wait", "", "#C2410C", "", "", ""),
    "off":  ("st-off",  "", "#6B6B6B", "", "", ""),
    "move": ("st-move", "", "#1A1A1A", "", "", ""),
    "soon": ("st-soon", "", "#1A1A1A", "", "", ""),
    "inv":  ("st-inv",  "", "#C2410C", "", "", ""),
}
STATE_WORD = {"ok": "Confirmed", "wait": "Action needed: confirm on Zoom", "off": "Cancelled", "move": "Rescheduled",
              "soon": "Upcoming", "inv": "Invitation"}

# dark mode, by class: (selector, background, text colour, border colour)
_DARK = [
    (".dm-bg", "#111111", "", ""), (".dm-card", "#1B1B1B", "", "#2E2E2E"), (".dm-sub", "#222222", "", "#2E2E2E"),
    (".dm-ink", "", "#F4F4F5", ""), (".dm-body", "", "#D4D4D8", ""), (".dm-mut", "", "#A1A1AA", ""),
    (".dm-link", "", "#FF8544", ""), (".dm-line", "", "", "#2E2E2E"), (".btn2", "#1B1B1B", "#F4F4F5", "#3F3F46"),
    (".st-ok", "", "#4ADE80", ""), (".st-wait", "", "#FF8544", ""), (".st-off", "", "#A1A1AA", ""),
    (".st-move", "", "#F4F4F5", ""), (".st-soon", "", "#F4F4F5", ""), (".st-inv", "", "#FF8544", ""),
    (".ev-ok", "", "#5FC48E", ""), (".ev-warn", "", "#F5A35C", ""),
]

CSS_BASE = (
    "body{margin:0;padding:0;width:100%!important;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}"
    "table{border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt}"
    "a[x-apple-data-detectors]{color:inherit!important;text-decoration:none!important}"
    "@media only screen and (max-width:620px){"
    ".wrap{padding:24px 12px 32px!important}.card{padding:28px 20px!important}.evp{padding:16px!important}"
    ".h1{font-size:22px!important;line-height:28px!important}"
    ".stack,.bcell,.pcell,.btn{display:block!important}.stack,.bcell,.btnt{width:100%!important}"
    ".stack{text-align:left!important}.hdr-r{padding-top:8px!important}"
    ".kv-k{padding:12px 0 0!important}.kv-v{padding:2px 0 12px!important;border-top:0!important}"
    ".pcell{padding:0 0 6px!important}.pgap{display:none!important}"
    ".bcell{padding:0 0 8px!important}.btn{text-align:center!important}"
    "}"
)


def _dark_css() -> str:
    """The dark rules three times: the media query (Apple Mail, iOS, Outlook for Mac), then Outlook.com's [data-ogsb]
    (backgrounds) and [data-ogsc] (text and borders). Selectors that share a declaration are grouped, to stay small."""
    def decl(bg: str, fg: str, bd: str) -> str:
        return ";".join(f"{p}:{c}!important" for p, c in (("background-color", bg), ("color", fg), ("border-color", bd)) if c)

    def rules(prefix: str, pick) -> str:
        groups: dict[str, list[str]] = {}
        for s, bg, fg, bd in _DARK:
            d = decl(*pick(bg, fg, bd))
            if d:
                groups.setdefault(d, []).append(prefix + s)
        return "".join(f"{','.join(sels)}{{{d}}}" for d, sels in groups.items())

    media = rules("", lambda bg, fg, bd: (bg, fg, bd))
    return (":root{color-scheme:light dark;supported-color-schemes:light dark}"
            f"@media (prefers-color-scheme:dark){{{media}}}"
            + rules("[data-ogsb] ", lambda bg, fg, bd: (bg, "", ""))
            + rules("[data-ogsc] ", lambda bg, fg, bd: ("", fg, bd)))


CSS_DARK = _dark_css()


def _font(size: int, lh: int, weight: int = 400, color: str = INK) -> str:
    """Inline type: explicit properties (Outlook ignores the `font` shorthand), exact line height."""
    return (f"font-family:{SANS};font-size:{size}px;line-height:{lh}px;font-weight:{weight};color:{color};"
            "mso-line-height-rule:exactly;")


_TABLE = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'


# ---------------------------------------------------------------- components
def label(text: str, color: str = MUTE, cls: str = "dm-mut", style: str = "") -> str:
    """Section / eyebrow label: 11px bold, uppercase, tracked."""
    return (f'<div class="{cls}" style="{_font(11, 16, 700, color)}text-transform:uppercase;letter-spacing:0.6px;{style}">'
            f'{esc(text)}</div>')


def _a(url: str, text: str, weight: int = 500) -> str:
    """An inline link; `url` must already be safe_url()/company_link()/mailto output."""
    return f'<a href="{esc(url)}" class="dm-link" style="color:{ACCENT_TEXT};font-weight:{weight};text-decoration:none">{esc(text)}</a>'


def preheader(text: str) -> str:
    """The inbox preview line, then filler so the client does not pull body text into it."""
    return (f'<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all">'
            f'{esc(text)}</div><div style="display:none;max-height:0;overflow:hidden;mso-hide:all">{"&#847;&zwnj;&nbsp;" * 40}</div>')


LOGO = "logo.png"   # static/email/logo.png: the Champions Group logo (130 x 82), shown at 104 x 66
HOST_PHOTO = "host.png"   # static/email/host.png: Deep's photo (120 x 120), shown round at 40 x 40


def header(brand: str, eyebrow: str = "") -> str:
    """The Champions Group logo above the card: from EMAIL_ASSETS_URL, else inside the message (cid). Its alt text is
    the brand in Champions Orange, so it still reads with images blocked. Another brand gets its name as text.
    (`eyebrow` is kept for callers; the heading states the email's purpose instead.)"""
    if "champions" not in (brand or "").lower() or not (ASSETS / LOGO).is_file():
        return f'<div style="{_font(18, 24, 700, ACCENT)}letter-spacing:-0.2px">{esc(brand)}</div>'
    src = _src(image_base({}, "hosted"), LOGO)
    return (f'<img src="{esc(src)}" width="104" height="66" alt="{esc(brand)}" style="display:block;width:104px;height:66px;'
            f'border:0;outline:none;text-decoration:none;{_font(18, 24, 700, ACCENT)}">')


def pills(items: list[tuple[str, str]]) -> str:
    """The email's state above the heading, as words in the state colour: "Confirmed", "Rescheduled · Action needed".
    (The name stays from the earlier badge design.)"""
    words = []
    for state, word in items:
        cls, _g, fg, *_ = STATES[state]
        words.append(f'<span class="{cls}" style="color:{fg}">{esc(word or STATE_WORD[state])}</span>')
    sep = f'<span class="dm-mut" style="color:{MUTE}">&nbsp;&middot;&nbsp;</span>'
    return f'<div style="{_font(13, 18, 600, MUTE)}">{sep.join(words)}</div>'


def h1(text: str) -> str:
    """The heading; a long one (a lifecycle email's subject line) is set a step smaller."""
    if len(text or "") > 48:
        return f'<h1 class="dm-ink" style="margin:0;{_font(20, 28, 700)}letter-spacing:-0.2px">{esc(text)}</h1>'   # no mobile bump
    return f'<h1 class="h1 dm-ink" style="margin:0;{_font(24, 32, 700)}letter-spacing:-0.3px">{esc(text)}</h1>'


def lead(paragraphs: list[str]) -> str:
    """The opening paragraphs (16/24, body colour)."""
    return "".join(f'<p class="dm-body" style="margin:{12 if i else 0}px 0 0;{_font(16, 24, 400, BODY)}">{esc(t)}</p>'
                   for i, t in enumerate(p for p in paragraphs if p))


def notice(text: str, bar: str = "", *, rich: bool = False) -> str:
    """A late update ("the visitor has already cancelled") in a quiet grey panel. `rich`: `text` is already-escaped HTML.
    (`bar` is kept for callers; the design has no coloured bars.)"""
    if not text:
        return ""
    return (f'<table {_TABLE} width="100%" class="dm-sub dm-line" bgcolor="{SUBTLE}" style="background-color:{SUBTLE};'
            f'border:1px solid {LINE};border-radius:6px;border-collapse:separate"><tr>'
            f'<td class="dm-ink" style="padding:12px 16px;{_font(14, 21, 400)}">{text if rich else esc(text)}</td></tr></table>')


_callout = notice   # for callers whose own parameter is called `notice`


def status_note(text: str, state: str, *, rich: bool = False) -> str:
    """What happens next, as a plain paragraph (15/23, body colour)."""
    if not text:
        return ""
    return f'<p class="dm-body" style="margin:0;{_font(15, 23, 400, BODY)}">{text if rich else esc(text)}</p>'


def date_tile(start: datetime, state: str) -> str:
    """56px live-text calendar leaf: month in Champions Orange (grey once cancelled), the day, the weekday."""
    off = state == "off"
    month_color, month_cls = (MUTE, "dm-mut") if off else (ACCENT_TEXT, "dm-link")
    return (f'<table {_TABLE} width="56" style="width:56px;border-collapse:separate">'
            f'<tr><td class="dm-card dm-line" bgcolor="{SURFACE}" align="center" style="background-color:{SURFACE};border:1px solid {LINE};'
            f'border-radius:8px;padding:7px 0 8px;text-align:center">'
            f'<div class="{month_cls}" style="{_font(11, 14, 700, month_color)}text-transform:uppercase;letter-spacing:0.6px">'
            f'{esc(start.strftime("%b").upper())}</div>'
            f'<div class="{"dm-mut" if off else "dm-ink"}" style="{_font(22, 26, 700, MUTE if off else INK)}">{start.day}</div>'
            f'<div class="dm-mut" style="{_font(11, 14, 400, MUTE)}">{esc(start.strftime("%a"))}</div></td></tr></table>')


def time_lines(start: datetime, duration: Any = None, muted: bool = False) -> str:
    """The date line and the time line ('6:30 PM IST (45 minutes)') next to the tile."""
    color, cls = (MUTE, "dm-mut") if muted else (INK, "dm-ink")
    dur = f' <span class="dm-mut" style="color:{MUTE}">({esc(duration)} minutes)</span>' if duration else ""
    return (f'<div class="{cls}" style="{_font(17, 24, 600, color)}">{esc(fmt_date(start))}</div>'
            f'<div class="{cls}" style="{_font(15, 22, 400, color)}">{esc(fmt_time(start))}{dur}</div>')


def _lines(value: str | tuple[str, ...] | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else [x for x in value if x]


def time_change(old: str | tuple[str, ...], new: str | tuple[str, ...], note: str = "") -> str:
    """Before and after, stacked: the old time muted and struck through, the new one prominent with an accent bar.
    Each side is a string or its lines (date, then time); `note` is a small muted line under the new time (duration)."""
    lab = f"{_font(11, 16, 700, MUTE)}text-transform:uppercase;letter-spacing:0.6px"
    was = "<br>".join(esc(x) for x in _lines(old))
    now = _lines(new)
    now_html = (f'<div class="dm-ink" style="{_font(17, 24, 600)}">{esc(now[0])}</div>'
                + "".join(f'<div class="dm-ink" style="{_font(15, 22, 400)}">{esc(x)}</div>' for x in now[1:])
                + (f'<div class="dm-mut" style="{_font(13, 18, 400, MUTE)}">{esc(note)}</div>' if note else ""))
    return (f'<table {_TABLE} width="100%" class="dm-sub" bgcolor="{SUBTLE}" style="background-color:{SUBTLE};border-collapse:separate;border-radius:10px">'
            f'<tr><td class="dm-mut" width="44" valign="top" style="width:44px;padding:12px 0 8px 14px;{lab}">Was</td>'
            f'<td class="dm-mut" valign="top" style="padding:12px 14px 8px 15px;{_font(14, 20, 400, MUTE)}text-decoration:line-through">{was}</td></tr>'
            f'<tr><td class="dm-mut" valign="top" style="padding:8px 0 12px 14px;{lab}">Now</td>'
            f'<td valign="top" style="padding:8px 14px 12px 12px;border-left:3px solid {ACCENT}">{now_html}</td></tr></table>')


def kv_table(rows: list[tuple[str, str]]) -> str:
    """Key/value rows (key text escaped here, values are already-escaped HTML); hairlines between rows."""
    rows = [(k, v) for k, v in rows if v]
    if not rows:
        return ""
    out = []
    for i, (k, v) in enumerate(rows):
        rule = f"border-top:1px solid {LINE};" if i else ""
        line = " dm-line" if i else ""
        out.append(f'<tr><td class="stack kv-k dm-mut{line}" width="104" valign="top" style="width:104px;{rule}padding:8px 16px 8px 0;'
                   f'{_font(13, 22, 500, MUTE)}">{esc(k)}</td>'
                   f'<td class="stack kv-v dm-ink{line}" valign="top" style="{rule}padding:8px 0;{_font(15, 22, 500)}">{v}</td></tr>')
    return f'<table {_TABLE} width="100%">{"".join(out)}</table>'


def event_card(title: str, state: str, rows: list[tuple[str, str]], *, start: datetime | None = None,
               duration: Any = None, when: str = "", change: tuple | None = None) -> str:
    """The call: its title, the date tile with the time (or the before-and-after block for a move), then the facts.
    Without a start time there is no tile; a known label shows as a 'When' row instead."""
    parts = [f'<div class="dm-ink" style="{_font(16, 24, 700)}">{esc(title)}</div>']
    if start:
        right = time_change(*change) if change else time_lines(start, duration, muted=state == "off")
        parts.append(f'<table {_TABLE} width="100%" style="margin-top:12px"><tr><td width="56" valign="top" style="width:56px;padding-top:12px">'
                     f'{date_tile(start, state)}</td><td width="16" style="width:16px;font-size:0;line-height:0">&nbsp;</td>'
                     f'<td valign="top" style="padding-top:12px">{right}</td></tr></table>')
    elif when:
        rows = [("When", esc(when))] + rows
    facts = kv_table(rows)
    if facts:
        parts.append(f'<div style="padding-top:16px">{facts}</div>')
    return (f'<table {_TABLE} width="100%" class="dm-line" style="border:1px solid {LINE};border-radius:8px;border-collapse:separate">'
            f'<tr><td class="evp" style="padding:20px 24px">{"".join(parts)}</td></tr></table>')


def buttons(actions: list[tuple[str, str] | None]) -> str:
    """Bulletproof buttons, primary first: a VML roundrect for Outlook desktop and a styled link for everyone else.
    Only safe http(s) URLs; an action without one is left out. Any second button is secondary (outlined)."""
    acts = [(t, safe_url(u)) for t, u in (a for a in actions if a) if safe_url(u)]
    cells = []
    for i, (t, u) in enumerate(acts):
        fill, stroke, color = (SURFACE, LINE_STRONG, INK) if i else (ACCENT, ACCENT, "#FFFFFF")
        w = max(140, 44 + round(8.6 * len(t)))
        uu, tt = esc(u), esc(t)
        cells.append(
            f'<td class="bcell" style="padding:0 8px 0 0">'
            f'<!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{uu}" '
            f'style="height:44px;v-text-anchor:middle;width:{w}px" arcsize="14%" strokecolor="{stroke}" fillcolor="{fill}"><w:anchorlock/>'
            f'<center style="color:{color};font-family:\'Segoe UI\',Arial,sans-serif;font-size:15px;font-weight:600">{tt}</center></v:roundrect><![endif]-->'
            f'<!--[if !mso]><!--><a href="{uu}" class="btn{" btn2" if i else ""}" style="display:inline-block;background-color:{fill};'
            f'border:1px solid {stroke};border-radius:6px;color:{color};font-family:{SANS};font-size:15px;line-height:20px;font-weight:600;'
            f'padding:12px 22px;text-decoration:none">{tt}</a><!--<![endif]--></td>')
    return f'<table {_TABLE} class="btnt"><tr>{"".join(cells)}</tr></table>' if cells else ""


def footer(brand: str, note: str, sent_line: str = "") -> str:
    """Brand, one helpful line, the site. (`sent_line` is kept for callers; the design leaves the machine line out.)"""
    site = (settings.site_base_url or "").replace("https://", "").replace("http://", "").rstrip("/")
    lines = [(t, w) for t, w in ((brand, 600), (note, 400), ((settings.email_postal_address or "").strip(), 400), (site, 400)) if t]
    return "".join(f'<div class="dm-mut" style="{_font(12, 18, w, MUTE)}padding-top:{6 if i else 0}px;text-align:center">'
                   f'{esc(t)}</div>' for i, (t, w) in enumerate(lines))


def sent_line(recipient: str, sent: datetime) -> str:
    sender = (settings.email_from or "").strip()
    return (f"Sent from {sender} " if sender else "Sent ") + f"to {recipient or 'you'} · {fmt_sent(sent)}"


def brief_section(text: str) -> str:
    """The pre-call brief as its own section: a hairline, then the brief (its first UPPERCASE line is the label)."""
    if not text:
        return ""
    return (f'<table {_TABLE} width="100%"><tr><td class="dm-line" style="border-top:1px solid {LINE};padding-top:24px">'
            f'{_brief_html(text)}</td></tr></table>')


def ask_panel(ask: dict[str, Any] | None) -> str:
    """Ask Deep (app/email_ask.panel): a quiet grey panel, a heading, one line, the questions as a list of links (each
    row a full-width tap target) and "Ask Deep's assistant anything". No images, no VML; only safe http(s) links."""
    if not ask:
        return ""
    chips = [(t, safe_url(u)) for t, u in ask.get("chips") or [] if safe_url(u)]
    opener = safe_url(ask.get("open"))
    if not chips and not opener:
        return ""
    rows = "".join(
        f'<tr><td class="dm-line" style="border-top:1px solid {LINE};padding:11px 0">'
        f'<a href="{esc(u)}" class="dm-ink" style="{_font(15, 22, 500)}text-decoration:none;display:block">{esc(t)}'
        f'<span class="dm-link" style="color:{ACCENT_TEXT};font-weight:700">&nbsp;&rsaquo;</span></a></td></tr>'
        for t, u in chips)
    more = (f'<div style="padding-top:14px"><a href="{esc(opener)}" class="dm-link" style="{_font(14, 20, 600, ACCENT_TEXT)}'
            f'text-decoration:none">Ask Deep&rsquo;s assistant anything</a></div>' if opener else "")
    return (f'<table {_TABLE} width="100%" class="dm-sub dm-line" bgcolor="{SUBTLE}" style="background-color:{SUBTLE};'
            f'border:1px solid {LINE};border-radius:8px;border-collapse:separate"><tr><td class="evp" style="padding:20px 24px">'
            f'<div class="dm-ink" style="{_font(16, 24, 700)}">{esc(ask.get("heading") or "")}</div>'
            f'<div class="dm-body" style="{_font(14, 21, 400, BODY)}padding:4px 0 12px">{esc(ask.get("line") or "")}</div>'
            f'<table {_TABLE} width="100%">{rows}</table>{more}</td></tr></table>')


def calendar_links(title: str, start_utc: Any, duration: Any, location: str = "", details: str = "",
                   ics_url: str = "") -> str:
    """"Add to calendar: Google · Outlook · Apple" for a confirmed call: Google's and Outlook.com's add-event pages
    (prefilled; nothing is sent to us) and, for Apple Calendar or Outlook desktop, the signed .ics link when there is one."""
    if not isinstance(start_utc, datetime) or not start_utc.tzinfo:
        return ""
    from urllib.parse import urlencode

    end = start_utc + timedelta(minutes=int(duration or 30))
    a, b = start_utc.astimezone(timezone.utc), end.astimezone(timezone.utc)
    google = "https://calendar.google.com/calendar/render?" + urlencode(
        {"action": "TEMPLATE", "text": title, "dates": f"{a:%Y%m%dT%H%M%SZ}/{b:%Y%m%dT%H%M%SZ}", "details": details,
         "location": location})
    outlook = "https://outlook.live.com/calendar/0/deeplink/compose?" + urlencode(
        {"path": "/calendar/action/compose", "rru": "addevent", "subject": title, "startdt": a.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "enddt": b.strftime("%Y-%m-%dT%H:%M:%SZ"), "body": details, "location": location})
    links = [("Google", google), ("Outlook", outlook)] + ([("Apple", ics_url)] if safe_url(ics_url) else [])
    sep = f'<span class="dm-mut" style="color:{MUTE}">&nbsp;&middot;&nbsp;</span>'
    return (f'<div class="dm-mut" style="{_font(13, 20, 400, MUTE)}">Add to calendar:&nbsp; '
            + sep.join(_a(safe_url(u), t, 600) for t, u in links) + "</div>")


def card_stack(blocks: list[tuple[int, str]]) -> str:
    """The card's content as one column: (space above in px, html); empty blocks are skipped."""
    rows, first = [], True
    for gap, block in blocks:
        if not block:
            continue
        rows.append(f'<tr><td style="padding-top:{0 if first else gap}px">{block}</td></tr>')
        first = False
    return f'<table {_TABLE} width="100%">{"".join(rows)}</table>'


def shell(*, title: str, pre: str, brand: str, eyebrow: str, card: str, foot: str) -> str:
    """The document: head with both style blocks, the preheader, the 600px column with header, card and footer."""
    return f"""<!doctype html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{esc(title)}</title>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
<style>{CSS_BASE}</style>
<style>{CSS_DARK}</style>
</head>
<body class="dm-bg" style="margin:0;padding:0;background-color:{CANVAS}">
{preheader(pre)}
<table {_TABLE} width="100%" bgcolor="{CANVAS}" class="dm-bg" style="background-color:{CANVAS}">
<tr><td class="wrap" align="center" style="padding:32px 24px 48px">
<!--[if mso]><table {_TABLE} width="{MAX_W}"><tr><td><![endif]-->
<table {_TABLE} width="100%" style="max-width:{MAX_W}px;width:100%;border-collapse:separate">
<tr><td style="padding:0 4px 20px;text-align:left">{header(brand, eyebrow)}</td></tr>
<tr><td class="card dm-card" bgcolor="{SURFACE}" style="background-color:{SURFACE};border:1px solid {LINE};border-top:3px solid {ACCENT};border-radius:8px;padding:40px;text-align:left">{card}</td></tr>
<tr><td align="center" style="padding:24px 8px 0">{foot}</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr>
</table>
</body>
</html>"""


# ---------------------------------------------------------------- shared booking facts
def _platform(booking: dict[str, Any]) -> str:
    method = booking.get("method") or ""
    links = " ".join(str(booking.get(k) or "") for k in ("join_url", "handoff_url"))
    return "Zoom" if method in ("scheduler", "meeting", "handoff", "browser") or "zoom.us" in links else "Online"


def _mail(email: str) -> str:
    """A mailto link for a valid address, else the escaped text."""
    return _a(f"mailto:{email}", email, 400) if _email_ok(email) else esc(email)


def _fine(text: str, size: int = 12) -> str:
    """A small muted second line under a value."""
    return f'<div class="dm-mut" style="{_font(size, 18 if size < 14 else 20, 400, MUTE)}padding-top:2px">{esc(text)}</div>' if text else ""


def _meeting(booking: dict[str, Any]) -> str:
    """'ID 812 3456 7890 · Passcode 742913' (either id field, as the text part's meeting line), '' without an id."""
    mid = booking.get("meeting_id") or booking.get("zoom_meeting_id")
    return (f"ID {mid}" + (f" · Passcode {booking['passcode']}" if booking.get("passcode") else "")) if mid else ""


def _join_rows(booking: dict[str, Any], confirmed: bool) -> list[tuple[str, str]]:
    """The Join row (link + meeting ID) for a confirmed call; nothing while it is pending or cancelled."""
    if not confirmed:
        return []
    join, mid = safe_url(booking.get("join_url")), _meeting(booking)
    if not (join or mid):
        return []
    return [("Join" if join else "Meeting", (_a(join, "Join meeting", 600) if join else "") + _fine(mid))]


def _attendee(booking: dict[str, Any]) -> list[tuple[str, str]]:
    email = (booking.get("email") or "").strip()
    name = esc((booking.get("name") or "").strip())
    if not (name or email):
        return []
    return [("Attendee", name + (f'<div class="dm-mut" style="{_font(14, 20, 400, MUTE)}">{_mail(email)}</div>' if email else ""))]


def _guests(booking: dict[str, Any]) -> str:
    """One line per extra guest: name · email (a mailto link only for a valid address)."""
    lines = []
    for g in booking.get("attendees") or []:
        if not isinstance(g, dict) or not (g.get("email") or g.get("name")):
            continue
        em, nm = (g.get("email") or "").strip(), esc((g.get("name") or "").strip())
        lines.append('<div style="word-break:break-word">' + (nm + (" · " if em else "") if nm else "")
                     + (f'<span class="dm-mut" style="color:{MUTE};font-weight:400">{_mail(em)}</span>' if em else "") + "</div>")
    return "".join(lines)


def _visitor_time(booking: dict[str, Any], start_utc: Any) -> list[tuple[str, str]]:
    """Host emails: the visitor's own time next to the host's, when they are in another zone."""
    vtz = booking.get("visitor_tz")
    if not isinstance(start_utc, datetime) or not vtz or vtz in ("-", settings.host_timezone):
        return []
    vs = start_utc.astimezone(_tz(vtz))
    return [("Visitor time", esc(f"{fmt_date(vs)} · {fmt_time(vs)}"))]


def _host_row(v: dict[str, str]) -> list[tuple[str, str]]:
    """Who they meet: the photo (round, 40 px) beside the name and HOST_TITLE. The photo is HOST_PHOTO_URL (https only),
    else static/email/host.png like the logo (EMAIL_ASSETS_URL, else inside the message)."""
    name = (settings.host_full_name or "").strip() or v.get("host_name") or "Deep"
    title = (settings.host_title or "").strip()
    photo = safe_url(settings.host_photo_url)
    if not photo.startswith("https://"):
        photo = _src(image_base({}, "hosted"), HOST_PHOTO) if (ASSETS / HOST_PHOTO).is_file() else ""
    linkedin = safe_url(settings.host_linkedin_url)
    text = (f'<div class="dm-ink" style="{_font(15, 22, 600)}">{esc(name)}</div>'
            + (f'<div class="dm-mut" style="{_font(13, 18, 400, MUTE)}">{esc(title)}</div>' if title else "")
            + (f'<div style="padding-top:6px"><a href="{esc(linkedin)}" class="btn2" style="display:inline-block;'
               f'border:1px solid {LINE_STRONG};border-radius:4px;padding:2px 8px;{_font(12, 18, 600, "#0A66C2")}'
               f'text-decoration:none">LinkedIn</a></div>' if linkedin else ""))
    if not photo:
        return [("Host", text)]
    img = (f'<img src="{esc(photo)}" width="40" height="40" alt="{esc(name)}" style="display:block;width:40px;height:40px;'
           f'border:0;border-radius:20px;object-fit:cover">')
    return [("Host", f'<table {_TABLE}><tr><td width="40" valign="middle" style="width:40px;padding-right:12px">{img}</td>'
                     f'<td valign="middle">{text}</td></tr></table>')]


def _phone_row(booking: dict[str, Any], confirmed: bool) -> list[tuple[str, str]]:
    """Joining by phone, when the meeting ID is known: Zoom's list of local numbers, then the ID. (A call confirmed on
    Zoom's own page has no ID here; Zoom's invitation carries its numbers.)"""
    mid = booking.get("meeting_id") or booking.get("zoom_meeting_id")
    if not confirmed or not mid:
        return []
    return [("By phone", f'Call a {_a("https://zoom.us/zoomconference", "local Zoom number", 500)}, then enter meeting ID '
                         f'{esc(mid)}')]


def expect_section(lines: list[str]) -> str:
    """"What to expect": the call type's three lines (app/booking/availability.agenda)."""
    if not lines:
        return ""
    items = "".join(f'<li style="margin:0 0 6px">{esc(t)}</li>' for t in lines)
    return (f'<div class="dm-ink" style="{_font(15, 22, 700)}">What to expect</div>'
            f'<ul class="dm-body" style="margin:8px 0 0;padding:0 0 0 20px;{_font(15, 23, 400, BODY)}">{items}</ul>')


def _expect(booking: dict[str, Any]) -> str:
    from app.booking.availability import agenda

    return expect_section(agenda(booking.get("schedule_slug"), booking.get("schedule_name")))


def _calendar(booking: dict[str, Any], v: dict[str, str], start: datetime | None, confirmed: bool, guest: bool = False) -> str:
    """The "Add to calendar" line for a confirmed call. A guest never gets the .ics link: it carries the booker's
    manage token."""
    if not confirmed or not start:
        return ""
    join = safe_url(booking.get("join_url"))
    return calendar_links(f"{v['title']} with {v.get('host_name') or 'Deep'}", booking.get("start_utc"), booking.get("duration_min"),
                          location=join, details=f"Join Zoom: {join}" if join else "",
                          ics_url="" if guest else (booking.get("ics_url") or ""))


def booking_rows(booking: dict[str, Any], audience: str, confirmed: bool, start: datetime | None) -> list[tuple[str, str]]:
    """The key/value facts of the confirmation (#1, #2): Platform, Join (confirmed only), Attendee, Company, Guests, and
    for the host the visitor's time, the notes and where they came from. Values are escaped HTML."""
    rows: list[tuple[str, str]] = []
    if audience == "host" and start:
        rows += _visitor_time(booking, booking.get("start_utc"))
    if start:
        rows.append(("Platform", esc(_platform(booking))))
    rows += _join_rows(booking, confirmed)
    rows += _attendee(booking)
    company = (booking.get("company") or "").strip() or (booking.get("company_line") or "").strip()
    if company:
        href = company_link(company)
        detail = (booking.get("company_line") or "").strip() if audience == "host" else ""
        rows.append(("Company", (_a(href, company, 500) if href else esc(company))
                     + (f'<div class="dm-mut" style="{_font(14, 20, 400, MUTE)}">{esc(detail)}</div>' if detail and detail != company else "")))
    guests = _guests(booking)
    if guests:
        rows.append(("Guests", guests))
    if audience == "host":
        notes = (booking.get("notes") or booking.get("reason") or "").strip()
        if notes:
            rows.append(("Notes", esc(notes)))
        origin = (booking.get("origin") or "").strip()
        if origin:
            rows.append(("Where", esc(origin)))
    return rows


def _start(value: Any, tz: ZoneInfo) -> datetime | None:
    return value.astimezone(tz) if isinstance(value, datetime) and value.tzinfo else None


def _brand(tpl: dict[str, str]) -> str:
    return tpl.get("brand_default") or templates.DEFAULTS["brand_default"]


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _pending(booking: dict[str, Any], pending: bool | None) -> bool:
    """The caller's pending flag; without one, the send functions' own rule (app/booking/email.is_pending)."""
    if pending is not None:
        return bool(pending)
    from app.booking.email import is_pending

    return is_pending(booking)


# ---------------------------------------------------------------- the confirmation (#1 visitor, #2 host)
def render(booking: dict[str, Any], audience: str, tpl: dict[str, str] | None = None, now: datetime | None = None, *,
           brief: str = "", notice: str = "", cta_ok: bool = True, images: str = "hosted", pending: bool | None = None,
           ask: dict[str, Any] | None = None) -> str:
    """HTML for audience 'visitor' or 'host'. `booking` is the dict stored by app/booking/flow.py (or SAMPLE_BOOKING).
    `pending`: the send function's state (app/booking/email.is_pending when left out).
    Host extras: `brief` is the pre-call brief as text (app/precall.text), `notice` a late update shown at the top
    ("the visitor has already cancelled"), `cta_ok=False` drops the button (nothing left to view or join).
    The host's "View booking details" opens booking['host_url'] (/host/booking/{id}, app/host_page.py) and is left out
    without it; the visitor's opens their manage page. `images` is accepted for callers; the design has none."""
    tpl = tpl or templates.get_templates()
    confirmed = not _pending(booking, pending)
    if audience == "visitor":
        return _render_visitor_confirmation(booking, tpl, now, confirmed=confirmed, cta_ok=cta_ok, ask=ask)
    return _render_host_confirmation(booking, tpl, now, confirmed=confirmed, brief=brief, notice=notice, cta_ok=cta_ok)


def _render_visitor_confirmation(booking: dict[str, Any], tpl: dict[str, str], now: datetime | None, *, confirmed: bool,
                                 cta_ok: bool = True, ask: dict[str, Any] | None = None) -> str:
    """#1, the visitor's confirmation: "Your booking is confirmed" with the join link, or (pending_zoom) "Confirm your
    booking on Zoom" with the prefilled Zoom link as the button and no meeting link."""
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    copy = _copy("visitor", confirmed, v, tpl)
    brand = _brand(tpl)
    tz = _tz(booking.get("visitor_tz"))
    start = _start(booking.get("start_utc"), tz)
    state = "ok" if confirmed else "wait"

    # the visitor's button: Join Zoom once the meeting exists; while they still have to confirm, the prefilled Zoom link.
    # No "view booking details": the Ask Deep panel answers questions and moves or cancels the call
    confirm_url = safe_url(booking.get("handoff_url")) if not confirmed else ""
    join = safe_url(booking.get("join_url")) if confirmed else ""
    cta = ("Confirm on Zoom", confirm_url) if confirm_url else (("Join Zoom meeting", join) if join else None)
    cal = _calendar(booking, v, start, confirmed)

    card = card_stack([
        (0, pills([(state, STATE_WORD[state])])),
        (12, h1(copy["heading"])),
        (12, lead(copy["intro"] + [copy["intro2"]])),
        (24, event_card(v["title"], state, _host_row(v) + booking_rows(booking, "visitor", confirmed, start)
                        + _phone_row(booking, confirmed), start=start, duration=booking.get("duration_min"), when=v["date_visitor"])),
        (28, _expect(booking)),
        (24, status_note(copy["status"], state)),
        (20, buttons([cta]) if cta and cta_ok else ""),
        (16, cal),
        (32, ask_panel(ask)),
    ])
    return shell(title=copy["heading"], pre=copy["preheader"], brand=brand, eyebrow=copy["eyebrow"], card=card,
                 foot=footer(brand, FOOTER_NOTE["visitor"], sent_line(booking.get("email") or "", _now(now).astimezone(tz))))


def _render_host_confirmation(booking: dict[str, Any], tpl: dict[str, str], now: datetime | None, *, confirmed: bool,
                              brief: str = "", notice: str = "", cta_ok: bool = True) -> str:
    """#2, the host's "New booking confirmed" / "New booking request": the facts in the host's time zone (the visitor's
    time beside it), the notes, origin and guests, the button to the host's booking page, then the pre-call brief.
    Never the visitor's prefilled Zoom link or their manage page."""
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    copy = _copy("host", confirmed, v, tpl)
    brand = _brand(tpl)
    tz = _tz(settings.host_timezone)
    start = _start(booking.get("start_utc"), tz)
    state = "ok" if confirmed else "wait"
    host = safe_url(booking.get("host_url"))
    cta = ("View booking details", host) if host and cta_ok else None
    card = card_stack([
        (0, _callout(notice) if notice else ""),
        (20, pills([(state, STATE_WORD[state])])),
        (16, h1(copy["heading"])),
        (12, lead(copy["intro"] + [copy["intro2"]])),
        (24, event_card(v["title"], state, booking_rows(booking, "host", confirmed, start), start=start,
                        duration=booking.get("duration_min"), when=v["date"])),
        (24, status_note(copy["status"], state)),
        (32, buttons([cta]) if cta else ""),
        (32, brief_section(brief)),
    ])
    return shell(title=copy["heading"], pre=copy["preheader"], brand=brand, eyebrow=copy["eyebrow"], card=card,
                 foot=footer(brand, FOOTER_NOTE["host"], sent_line(settings.host_email, _now(now).astimezone(tz))))


# ---------------------------------------------------------------- the text part, read back (#3-#13)
_FACT = re.compile(r"^([A-Za-z ]{1,12}):(\s+)(.*)$")          # the same "Label:   value" rule as templates.html_wrap
_URL = re.compile(r"https?://[^\s<>\"']+")
GUEST_HELD = "The time is held while it is confirmed on Zoom; Zoom sends the meeting link once it is final."


def _link_label(url: str) -> str:
    """What a long link reads as in a sentence: host and path, no scheme or query (the href is the whole URL);
    escaped, with a break opportunity after each / so a narrow screen wraps it between words, not inside one."""
    p = urlsplit(url)
    shown = (p.netloc + p.path).rstrip("/")
    shown = shown if len(shown) <= 44 else shown[:42].rstrip("/.-") + "…"
    return esc(shown).replace("/", "/<wbr>")


def linkify(text: str) -> str:
    """Escaped text in which every safe http(s) URL is a link, as templates.html_wrap does for the simple card
    (trailing punctuation stays outside the link). Anything else that looks like a link stays text."""
    out, pos = [], 0
    for m in _URL.finditer(text or ""):
        raw = m.group(0).rstrip(".,;:!?)")
        out.append(esc(text[pos:m.start()]))
        u = safe_url(raw)
        out.append(f'<a href="{esc(u)}" class="dm-link" style="color:{ACCENT_TEXT};text-decoration:underline;word-break:break-word">'
                   f'{_link_label(u)}</a>' if u else esc(raw))
        pos = m.start() + len(raw)
    out.append(esc((text or "")[pos:]))
    return "".join(out)


def _is_signoff(lines: list[str]) -> bool:
    """'See you then, / Deep / example.com': up to three short lines, none of them a sentence."""
    return 0 < len(lines) <= 3 and all(len(t) <= 48 and not t.endswith((".", ":", "?", "!")) for t in lines)


def parse_body(body: str, meeting_line: str = "") -> dict[str, Any]:
    """The plain-text body as parts: intro paragraphs (before the first fact), facts [(label, value, [more lines])],
    outro paragraphs, the sign-off lines, and whether the meeting line (Meeting ID · Passcode) was there."""
    intro: list[list[str]] = []
    outro: list[list[str]] = []
    facts: list[tuple[str, str, list[str]]] = []
    meeting = False
    for block in re.split(r"\n[ \t]*\n", (body or "").strip()):
        had_facts, para, in_facts = bool(facts), [], False
        for ln in (x.strip() for x in block.splitlines()):
            if not ln:
                continue
            m = _FACT.match(ln)
            if m and m.group(2):
                facts.append((m.group(1).strip(), m.group(3).strip(), []))
                in_facts = True
            elif meeting_line and ln == meeting_line:
                meeting = True
            elif in_facts:
                facts[-1][2].append(ln)
            else:
                para.append(ln)
        if para:
            (outro if had_facts else intro).append(para)
    if not facts:                  # a letter without fact lines (the 24 h reminder): the card follows its first real paragraph
        cut = next((i + 1 for i, p in enumerate(intro) if not re.match(r"^(Hi|Hello|Dear)\b", p[0])), len(intro))
        intro, outro = intro[:cut], intro[cut:]
    signoff = outro.pop() if outro and _is_signoff(outro[-1]) else []
    return {"intro": intro, "facts": facts, "outro": outro, "signoff": signoff, "meeting": meeting}


def _prose(paras: list[list[str]], size: int = 15, lh: int = 24, gap: int = 12) -> str:
    return "".join(f'<p class="dm-body" style="margin:{gap if i else 0}px 0 0;{_font(size, lh, 400, BODY)}">'
                   + "<br>".join(linkify(t) for t in p) + "</p>" for i, p in enumerate(paras) if p)


def _day_word(start: datetime | None, now: datetime) -> str:
    """'Today' / 'Tomorrow' / 'Upcoming': the call's date against today's, both in the recipient's time zone."""
    if not start:
        return "Upcoming"
    days = (start.date() - now.astimezone(start.tzinfo).date()).days
    return "Today" if days == 0 else "Tomorrow" if days == 1 else "Upcoming"


def _letter(booking: dict[str, Any], *, tpl: dict[str, str], v: dict[str, str], audience: str, heading: str, body: str,
            eyebrow: str, states: list[tuple[str, str]], tz: ZoneInfo, now: datetime | None, recipient: str,
            actions: list[tuple[str, str] | None], pending: bool, cancelled: bool = False, moved: bool = False,
            old: tuple[str, ...] | None = None, brief: str = "", pre_extra: str = "", when: str = "",
            ask: dict[str, Any] | None = None, expect: bool = False) -> str:
    """One lifecycle email: pills, the heading (what the simple card showed as its title), the text part's opening
    paragraphs, the event card, its closing paragraphs (the next step as a note in the state colour), the buttons the
    send function chose, the sign-off, and for the host's day-before email the brief."""
    brand = _brand(tpl)
    now = _now(now)
    if brief:                                       # the brief closes the text part; here it gets its own section
        first = brief.strip().splitlines()[0].strip()
        lines = body.splitlines()
        cut = next((i for i, ln in enumerate(lines) if ln.strip() == first), None)
        if cut is not None:
            body, brief = "\n".join(lines[:cut]), "\n".join(lines[cut:])
    if audience != "host" and v.get("manage_line"):
        body = body.replace(v["manage_line"], "")
    parts = parse_body(body, v.get("meeting_line") or "")
    start = _start(booking.get("start_utc"), tz)
    confirmed = not pending and not cancelled
    action_urls = {safe_url(a[1]) for a in actions if a}
    facts = {label.lower(): value for label, value, _ in parts["facts"]}

    # the event card: the tile (or the before-and-after block), then the rows
    change = None
    if moved and start:
        was = old or ((facts["was"],) if facts.get("was") else None)
        if was:
            change = (was, (fmt_date(start), fmt_time(start)), f"{booking['duration_min']} minutes" if booking.get("duration_min") else "")
    rows: list[tuple[str, str]] = []
    if audience != "host" and not cancelled:
        rows += _host_row(v)
    if audience == "host" and start:
        rows += _visitor_time(booking, booking.get("start_utc"))
    if start and not cancelled:
        rows.append(("Platform", esc(_platform(booking))))
    rows += _join_rows(booking, confirmed)
    if audience != "host":
        rows += _phone_row(booking, confirmed)
    if audience == "host" and ("name" in facts or "email" in facts):
        rows += _attendee(booking)
    for label, value, more in parts["facts"]:
        key = label.lower()
        if key == "call" or key == "zoom" or (key in ("when", "now", "was") and start):
            continue                                # the card's title, the tile / before-and-after block, the Join row
        if audience == "host" and key in ("name", "email"):
            continue                                # the Attendee row
        if key == "booking page" and safe_url(value) in action_urls:
            continue                                # the "Open booking page" button carries it
        if key == "guests" and _guests(booking):
            rows.append(("Guests", _guests(booking)))
            continue
        if key == "company" and company_link(value):
            rows.append(("Company", _a(company_link(value), value, 500)))
            continue
        rows.append((label, linkify(value) + "".join(f'<div class="dm-mut" style="{_font(13, 20, 400, MUTE)}">{linkify(t)}</div>' for t in more)))
    state = states[0][0]
    card_html = event_card(v["title"], state, rows, start=start, duration=booking.get("duration_min"), change=change,
                           when=when if not start and not any(k in facts for k in ("when", "now", "was")) else "")

    # the closing paragraphs: the next step (and the guest's "held" line) as a note in the state colour
    notes = {GUEST_HELD} | {templates.render(templates.NEXT_STEP[k], v) for k in ("pending_zoom", "confirmed", "confirmed_nolink", "nudge", "handoff")}
    note_state = "wait" if pending and not cancelled else state
    outro = [(16, status_note(linkify(" ".join(p)), note_state, rich=True) if " ".join(p) in notes else _prose([p]))
             for p in parts["outro"]]
    if outro:
        outro[0] = (24, outro[0][1])
    signoff = (f'<p class="dm-body" style="margin:0;{_font(15, 22, 400, BODY)}">' + "<br>".join(linkify(t) for t in parts["signoff"]) + "</p>"
               if parts["signoff"] else "")
    intro_texts = [" ".join(p) for p in parts["intro"] if not re.match(r"^(Hi|Hello|Dear)\b", p[0])]
    pre = " ".join(x for x in ((intro_texts[0] if intro_texts else heading), pre_extra) if x)

    cal = _calendar(booking, v, start, confirmed, guest=audience == "guest") if audience != "host" else ""
    card = card_stack([
        (0, pills(states)),
        (12, h1(heading)),
        (12, _prose(parts["intro"], 16, 24)),
        (24, card_html),
        (28, _expect(booking) if expect and not cancelled else ""),
        *outro,
        (24, buttons(actions)),
        (16, cal),
        (28, signoff),
        (32, ask_panel(ask)),
        (32, brief_section(brief)),
    ])
    note = FOOTER_NOTE["host"] if audience == "host" else FOOTER_NOTE["visitor"]
    return shell(title=heading, pre=pre, brand=brand, eyebrow=eyebrow, card=card,
                 foot=footer(brand, note, sent_line(recipient, now.astimezone(tz))))


def _context(booking: dict[str, Any], audience: str, tpl: dict[str, str] | None) -> tuple[dict[str, str], dict[str, str], ZoneInfo, str]:
    tpl = tpl or templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    tz = _tz(settings.host_timezone if audience == "host" else booking.get("visitor_tz"))
    recipient = settings.host_email if audience == "host" else (booking.get("email") or "")
    return tpl, v, tz, recipient


def _who(v: dict[str, str]) -> str:
    return v.get("name") or "The visitor"


def _soon(word: str) -> str:
    return {"Today": "today", "Tomorrow": "tomorrow"}.get(word, "coming up")


def _host_extra(v: dict[str, str]) -> str:
    return " · ".join(x for x in (v["name"], v["title"], v["date"]) if x)


def render_cancelled(booking: dict[str, Any], audience: str, subject: str, body: str, tpl: dict[str, str] | None = None,
                     now: datetime | None = None, *, actions: list[tuple[str, str] | None] = (),
                     ask: dict[str, Any] | None = None) -> str:
    """#3 (visitor) / #4 (host): the cancelled call and its time, calm slate, no join link."""
    tpl, v, tz, to = _context(booking, audience, tpl)
    heading = f"{_who(v)} cancelled their call" if audience == "host" else "Your call has been cancelled"
    return _letter(booking, tpl=tpl, v=v, audience=audience, heading=heading, body=body, eyebrow="Booking cancelled",
                   states=[("off", "")], tz=tz, now=now, recipient=to, actions=list(actions), pending=False, cancelled=True,
                   pre_extra=_host_extra(v) if audience == "host" else "", ask=ask if audience == "visitor" else None)


def render_moved(booking: dict[str, Any], audience: str, subject: str, body: str, tpl: dict[str, str] | None = None,
                 now: datetime | None = None, *, pending: bool, actions: list[tuple[str, str] | None] = (),
                 ask: dict[str, Any] | None = None) -> str:
    """#5 (visitor) / #6 (host): the before-and-after block; a hold still to confirm on Zoom says so."""
    tpl, v, tz, to = _context(booking, audience, tpl)
    prev = _start(booking.get("previous_start_utc"), tz)
    heading = (f"{_who(v)} rescheduled their call" if audience == "host"
               else "Confirm your new time on Zoom" if pending else "Your call has been rescheduled")
    return _letter(booking, tpl=tpl, v=v, audience=audience, heading=heading, body=body, eyebrow="Booking rescheduled",
                   states=[("move", "")] + ([("wait", "")] if pending else []), tz=tz, now=now, recipient=to,
                   actions=list(actions), pending=pending, moved=True,
                   old=(fmt_date(prev), fmt_time(prev)) if prev else None, pre_extra=_host_extra(v) if audience == "host" else "",
                   ask=ask if audience == "visitor" else None)


def render_reminder(booking: dict[str, Any], subject: str, body: str, tpl: dict[str, str] | None = None,
                    now: datetime | None = None, *, pending: bool, actions: list[tuple[str, str] | None] = (),
                    ask: dict[str, Any] | None = None) -> str:
    """#7, the visitor's day-before reminder."""
    tpl, v, tz, to = _context(booking, "visitor", tpl)
    word = _day_word(_start(booking.get("start_utc"), tz), _now(now))
    heading = "Confirm your time on Zoom" if pending else f"Your call with {v.get('host_name') or 'Deep'} is {_soon(word)}"
    return _letter(booking, tpl=tpl, v=v, audience="visitor", heading=heading, body=body, eyebrow="Reminder",
                   states=[("soon", word)] + ([("wait", "")] if pending else []), tz=tz, now=now, recipient=to,
                   actions=list(actions), pending=pending, ask=ask, expect=True)


def render_host_brief(booking: dict[str, Any], subject: str, body: str, brief: str, tpl: dict[str, str] | None = None,
                      now: datetime | None = None, *, today: bool, pending: bool, actions: list[tuple[str, str] | None] = ()) -> str:
    """#8, the host's day-before email: the call in the host's time with the visitor's beside it, then the brief.
    `today` is the send function's own "today / tomorrow" decision, so the pill and the subject agree."""
    tpl, v, tz, to = _context(booking, "host", tpl)
    heading = f"Your call with {_who(v)} is {'today' if today else 'tomorrow'}"
    return _letter(booking, tpl=tpl, v=v, audience="host", heading=heading, body=body, eyebrow="Pre-call brief",
                   states=[("soon", "Today" if today else "Tomorrow")] + ([("wait", "")] if pending else []), tz=tz, now=now,
                   recipient=to, actions=list(actions), pending=pending, brief=brief, pre_extra=_host_extra(v))


def render_nudge(lead: dict[str, Any], subject: str, body: str, tpl: dict[str, str] | None = None,
                 now: datetime | None = None, *, ask: dict[str, Any] | None = None) -> str:
    """#9, the one reminder 24 h after an unconfirmed Zoom hand-off: the wanted time, the call type and the same
    prefilled link as the button. `lead` is app/nudge.lead_for_email's dict."""
    tpl = tpl or templates.get_templates()
    v = templates.build_vars(lead, tpl)
    tz = _tz(lead.get("visitor_tz") if lead.get("visitor_tz") not in (None, "-") else None)
    booking = {"method": "handoff", "handoff_url": lead.get("handoff_url"), "start_utc": lead.get("slot_start"),
               "duration_min": lead.get("duration_min"), "email": lead.get("email")}
    return _letter(booking, tpl=tpl, v=v, audience="visitor", heading="Your time isn’t reserved yet", body=body,
                   eyebrow="Booking request",
                   states=[("wait", "")], tz=tz, now=now, recipient=lead.get("email") or "",
                   actions=[("Confirm on Zoom", lead.get("handoff_url") or "")], pending=True, when=v["date_visitor"], ask=ask)


GUEST_EYEBROW = {"booked": "Invitation", "moved": "Booking rescheduled", "cancelled": "Booking cancelled", "reminder": "Reminder"}


def render_guest(booking: dict[str, Any], guest: dict[str, str], kind: str, subject: str, body: str,
                 tpl: dict[str, str] | None = None, now: datetime | None = None, *, pending: bool,
                 actions: list[tuple[str, str] | None] = (), ask: dict[str, Any] | None = None) -> str:
    """#10-#13, an extra guest's note (app/booking/email.attendee_notice): invited, moved, cancelled or reminder.
    Written to the guest: the card has no Guests row of its own, the text's With line names the others."""
    tpl = tpl or templates.get_templates()
    v = templates.build_vars(templates.booking_to_lead(booking), tpl)
    tz = _tz(booking.get("visitor_tz"))
    cancelled = kind == "cancelled"
    first = {"booked": ("inv", ""), "moved": ("move", ""), "cancelled": ("off", ""),
             "reminder": ("soon", _day_word(_start(booking.get("start_utc"), tz), _now(now)))}.get(kind, ("soon", ""))
    states = [first] + ([("wait", "")] if pending and not cancelled else [])
    prev = _start(booking.get("previous_start_utc"), tz)
    host = v.get("host_name") or "Deep"
    heading = {"booked": f"{v.get('name') or 'A colleague'} invited you to a call with {host}", "moved": "Your call has a new time",
               "cancelled": "This call has been cancelled"}.get(kind) or f"Your call with {host} is {_soon(first[1])}"
    return _letter(dict(booking, attendees=[]), tpl=tpl, v=v, audience="guest", heading=heading, body=body,
                   eyebrow=GUEST_EYEBROW.get(kind, "Reminder"), states=states, tz=tz, now=now,
                   recipient=guest.get("email") or "", actions=list(actions), pending=pending, cancelled=cancelled,
                   moved=kind == "moved", old=(fmt_date(prev), fmt_time(prev)) if prev and kind == "moved" else None, ask=ask,
                   expect=kind in ("booked", "reminder"))


# ---------------------------------------------------------------- the pre-call brief (host emails)
# the evidence tag precall.text appends to every WHY THIS SCORE line (always the system's, never visitor or model text)
_EV_TAG = re.compile(r"\s\[(checked(: [a-z ]+)?|seen|warning)\]$")
_EV_COLOR = {"checked": ("#257A4D", "ev-ok"), "seen": (MUTE, "dm-mut"), "warning": ("#B54708", "ev-warn")}


def _ev_tag(item: str) -> str:
    """An escaped WHY THIS SCORE bullet with its trailing tag as a small coloured span."""
    m = _EV_TAG.search(item)
    if not m:
        return item
    color, cls = _EV_COLOR[m.group(1).split(":")[0]]
    return (item[:m.start()] + f' <span class="{cls}" style="font-family:{SANS};font-size:12px;line-height:18px;color:{color};white-space:nowrap">'
            f'[{m.group(1)}]</span>')


def _brief_html(text: str) -> str:
    """The pre-call brief (app/precall.text): UPPERCASE lines are headings, 'Key:  value' lines a fact table, '• ' bullets.
    Only under WHY THIS SCORE is a bullet's trailing [checked…] / [seen] / [warning] tag styled: elsewhere (what they
    say, talking points, watch out) the text can come from the visitor or the model, so a tag there stays plain text."""
    out, rows, items = [], [], []
    heading = ""

    def flush():
        if rows:
            out.append(f'<table {_TABLE} width="100%" style="margin:4px 0 8px">' + "".join(rows) + "</table>")
            rows.clear()
        if items:
            out.append(f'<ul class="dm-ink" style="margin:4px 0 8px;padding:0 0 0 18px;{_font(14, 21, 400)}">'
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
            heading = t.strip()
            out.append(label(heading, style=f"padding:{24 if out else 0}px 0 8px"))
        elif m:
            rule, line = (f"border-top:1px solid {SUBTLE};", " dm-line") if rows else ("", "")
            rows.append(f'<tr><td class="dm-mut{line}" width="120" valign="top" style="width:120px;{rule}padding:6px 16px 6px 0;'
                        f'{_font(13, 20, 400, MUTE)}">{esc(m.group(1))}</td>'
                        f'<td class="dm-ink{line}" valign="top" style="{rule}padding:6px 0;{_font(14, 20, 400)}">{esc(m.group(2))}</td></tr>')
        elif t.lstrip().startswith("• "):
            if rows:
                flush()
            item = esc(t.lstrip()[2:])
            items.append(_ev_tag(item) if heading == "WHY THIS SCORE" else item)
        else:
            flush()
            out.append(f'<p class="dm-ink" style="margin:0 0 8px;{_font(14, 21, 400)}">{esc(t)}</p>')
    flush()
    return "".join(out)
