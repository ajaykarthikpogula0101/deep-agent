"""The README's animated graphics, in one restrained style: deep ink navy, one soft indigo accent, hairline borders,
monoline icons, light type weights and slow motion. Pure SVG + SMIL, so they animate on GitHub as <img>.

    python scripts/readme_graphics.py

  header.svg    title, tagline and a mini chat that plays on a loop
  meta.svg      the stack on the left, the quality checks on the right
  features.svg  twelve capabilities, a spotlight moving through them
  backend.svg   the FastAPI core and its ten modules, data flowing in
  pipeline.svg  how one question is answered, step by step
  newsloop.svg  how News checks itself
  jobs.svg      the scheduled jobs in four lanes
  divider.svg   a hairline with a light travelling along it
"""
import math
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"
SANS = "Inter, 'SF Pro Display', 'Segoe UI', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
MONO = "'JetBrains Mono', 'SF Mono', Consolas, Menlo, monospace"
INK, INK2, INK3 = "#0A0E27", "#12123D", "#231D63"
ACCENT, ACCENT2, SOFT = "#7B6CF6", "#A59BFF", "#B8BBDA"

# monoline icons on a 24-unit grid (stroke only)
ICONS = {
    "chat": '<path d="M20.5 11.5a8 8 0 0 1-11.7 7.1L4 20l1.4-4.6A8 8 0 1 1 20.5 11.5z"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="3.8" ry="9"/><path d="M3 12h18"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    "news": '<rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="M7.5 8.5h9M7.5 12h9M7.5 15.5h5.5"/>',
    "bolt": '<path d="M13 2.5 4.5 13.5h6.5l-1 8 8.5-11h-6.5z"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2.2 4.8-4.8 2.2 2.2-4.8z"/>',
    "clipboard": '<rect x="5" y="4.5" width="14" height="16.5" rx="2.5"/><rect x="9" y="2.5" width="6" height="4" rx="1.2"/><path d="M8.5 11h7M8.5 14.5h4.5"/>',
    "users": '<circle cx="9" cy="8.5" r="3.4"/><path d="M3 20c.4-3.3 2.9-5.6 6-5.6s5.6 2.3 6 5.6"/><circle cx="17" cy="9.5" r="2.5"/><path d="M15.8 14.4c2.6.3 4.6 2.3 5 5.1"/>',
    "trend": '<path d="m3.5 16.5 5.5-5.5 4 4 7.5-7.5"/><path d="M15 7.5h5.5V13"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
    "bell": '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    "shield": '<path d="M12 3 19.5 6v5.5c0 4.6-3.2 8-7.5 9.5-4.3-1.5-7.5-4.9-7.5-9.5V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    "database": '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8v-13"/><path d="M4.5 12c0 1.6 3.4 2.8 7.5 2.8s7.5-1.2 7.5-2.8"/>',
    "book": '<path d="M4.5 18.5V5.5a2 2 0 0 1 2-2h13v15h-13a2 2 0 0 0-2 2 2 2 0 0 0 2 2h13"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
    "layers": '<path d="M12 3.5 3 8.2l9 4.7 9-4.7z"/><path d="m3 12.4 9 4.7 9-4.7"/><path d="m3 16.6 9 4.7 9-4.7"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m20 20-4.8-4.8"/>',
    "spark": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/>',
    "send": '<path d="M21 3 10.5 13.5"/><path d="M21 3 14.5 21l-4-7.5L3 9.5z"/>',
    "pulse": '<path d="M3 12h4l2.5-6.5 5 13 2.5-6.5H21"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5V12l3 2"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.2 2.4 2.4 4.6-4.8"/>',
    "download": '<path d="M12 3.5v11M7.5 10l4.5 4.5 4.5-4.5M4.5 20h15"/>',
    "code": '<path d="m8.5 7-5 5 5 5M15.5 7l5 5-5 5"/>',
    "save": '<path d="M5 3.5h11l3 3v14H5z"/><path d="M8.5 3.5v4.5h6V3.5M8.5 20.5v-6h7v6"/>',
    "refresh": '<path d="M19.5 10.5A7.7 7.7 0 0 0 5.2 8M4.5 4v4.2h4.2"/><path d="M4.5 13.5A7.7 7.7 0 0 0 18.8 16M19.5 20v-4.2h-4.2"/>',
}


def icon(name, x, y, size=22, color=ACCENT2, width=1.6):
    s = size / 24
    return (f'<g transform="translate({x - size / 2:.1f} {y - size / 2:.1f}) scale({s:.3f})" fill="none" stroke="{color}" '
            f'stroke-width="{width / s:.2f}" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')


def e(s):
    return escape(s, quote=True)


def defs(w, h):
    return f'''  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{INK}"/>
      <stop offset=".6" stop-color="{INK2}"><animate attributeName="stop-color" values="{INK2};#17164A;{INK2}" dur="16s" repeatCount="indefinite"/></stop>
      <stop offset="1" stop-color="{INK3}"><animate attributeName="stop-color" values="{INK3};#2D2580;{INK3}" dur="16s" repeatCount="indefinite"/></stop>
    </linearGradient>
    <radialGradient id="ga"><stop offset="0" stop-color="{ACCENT}" stop-opacity=".32"/><stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></radialGradient>
    <radialGradient id="gb"><stop offset="0" stop-color="#4F8CFF" stop-opacity=".16"/><stop offset="1" stop-color="#4F8CFF" stop-opacity="0"/></radialGradient>
    <radialGradient id="core" cx=".35" cy=".3"><stop offset="0" stop-color="#9A8DFF"/><stop offset=".65" stop-color="#5E4FE8"/><stop offset="1" stop-color="#2D2580"/></radialGradient>
    <linearGradient id="card" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".065"/><stop offset="1" stop-color="#fff" stop-opacity=".025"/></linearGradient>
    <linearGradient id="edge" x1="0" x2="1"><stop offset="0" stop-color="{ACCENT2}"/><stop offset="1" stop-color="#6FA8FF"/></linearGradient>
    <linearGradient id="hair" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".18"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
    <filter id="soft" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="3.5"/></filter>
    <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/><feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 .035 0"/></filter>
    <clipPath id="clip"><rect width="{w}" height="{h}" rx="22"/></clipPath>
  </defs>'''


def frame(w, h, body, title):
    """The shared backdrop: ink gradient that slowly breathes, two soft glows, fine grain, a hairline border."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{e(title)}">
  <title>{e(title)}</title>
{defs(w, h)}
  <g clip-path="url(#clip)" font-family="{SANS}">
    <rect width="{w}" height="{h}" fill="url(#bg)"/>
    <circle cx="{w * .84:.0f}" cy="{h * .08:.0f}" r="{max(h * .75, 260):.0f}" fill="url(#ga)"><animate attributeName="cx" values="{w * .84:.0f};{w * .74:.0f};{w * .84:.0f}" dur="20s" repeatCount="indefinite"/></circle>
    <circle cx="{w * .1:.0f}" cy="{h:.0f}" r="{max(h * .6, 220):.0f}" fill="url(#gb)"><animate attributeName="cx" values="{w * .1:.0f};{w * .2:.0f};{w * .1:.0f}" dur="24s" repeatCount="indefinite"/></circle>
    <rect width="{w}" height="{h}" filter="url(#grain)"/>
{body}
    <rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="21.5" fill="none" stroke="#fff" stroke-opacity=".09"/>
  </g>
</svg>
'''


def heading(x, y, kicker, title, anchor="start"):
    return (f'    <text x="{x}" y="{y}" text-anchor="{anchor}" font-size="11.5" font-weight="600" letter-spacing="3.2" fill="{ACCENT2}">{e(kicker)}</text>\n'
            f'    <text x="{x}" y="{y + 30}" text-anchor="{anchor}" font-size="23" font-weight="600" letter-spacing="-.3" fill="#F4F4FF">{e(title)}</text>\n')


def fade_in(begin, dx=0, dy=8, dur=.8):
    return (f'<animate attributeName="opacity" from="0" to="1" begin="{begin:.2f}s" dur="{dur}s" fill="freeze"/>'
            f'<animateTransform attributeName="transform" type="translate" from="{dx} {dy}" to="0 0" begin="{begin:.2f}s" dur="{dur}s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines=".2 .7 .2 1"/>')


def spotlight(i, n, dur, lo, hi):
    a, b, c = i / n, (i + .5) / n, (i + 1) / n
    return f'values="{lo};{lo};{hi};{lo};{lo}" keyTimes="0;{a:.4f};{b:.4f};{c:.4f};1" dur="{dur}s" repeatCount="indefinite"'


def chip(x, y, w, h=34, r=17):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="#fff" fill-opacity=".05" stroke="#fff" stroke-opacity=".12"/>'


def write(name, svg):
    (OUT / name).write_text(svg, encoding="utf-8", newline="\n")


# ------------------------------------------------------------------ header
W, H = 1200, 360
body = f'''    <g opacity="0">{fade_in(.1)}
      <rect x="64" y="58" width="36" height="36" rx="10" fill="none" stroke="{ACCENT2}" stroke-opacity=".7"/>
      <text x="82" y="81.5" text-anchor="middle" font-family="{MONO}" font-size="14" font-weight="600" fill="{ACCENT2}">&gt;_</text>
      <text x="116" y="81" xml:space="preserve" font-size="12" font-weight="600" letter-spacing="3.4" fill="{SOFT}">CHAMPIONS GROUP   <tspan fill="{ACCENT}">—</tspan>   <tspan font-weight="500" fill-opacity=".75">DEEPENDHQ.COM</tspan></text>
    </g>
    <clipPath id="type"><rect x="56" y="110" width="0" height="110"><animate attributeName="width" from="0" to="600" begin=".35s" dur="1.6s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines=".45 0 .2 1"/></rect></clipPath>
    <g clip-path="url(#type)">
      <text x="60" y="196" font-size="84" font-weight="700" letter-spacing="-3" fill="#F7F7FF">ask deep<tspan font-family="{MONO}" font-weight="500" font-size="64" fill="{ACCENT2}" dx="22">&gt;</tspan><tspan font-family="{MONO}" font-weight="500" font-size="64" fill="{ACCENT2}">_<animate attributeName="fill-opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" dur="1.2s" repeatCount="indefinite"/></tspan></text>
    </g>
    <g opacity="0">{fade_in(1.8)}
      <text x="62" y="240" font-size="21" font-weight="400" fill="#D9DBF2">The AI messenger that answers with sources,</text>
      <text x="62" y="268" font-size="21" font-weight="400" fill="#D9DBF2">books calls and keeps the news fresh.</text>
    </g>
    <g opacity="0" font-size="11.5" font-weight="600" letter-spacing="2.6" fill="{SOFT}">{fade_in(2.3)}
      <text x="62" y="312">ANSWERS</text><circle cx="152" cy="308" r="2" fill="{ACCENT}"/>
      <text x="166" y="312">BOOKINGS</text><circle cx="265" cy="308" r="2" fill="{ACCENT}"/>
      <text x="279" y="312">NEWS</text><circle cx="339" cy="308" r="2" fill="{ACCENT}"/>
      <text x="353" y="312">BRIEFS</text><circle cx="434" cy="308" r="2" fill="{ACCENT}"/>
      <text x="448" y="312">VOICE</text>
    </g>
    <g transform="translate(804 56)"><g opacity="0">{fade_in(.6, 0, 12, 1)}
      <rect width="332" height="250" rx="18" fill="#fff" fill-opacity=".045" stroke="#fff" stroke-opacity=".12"/>
      <circle cx="28" cy="28" r="12" fill="none" stroke="{ACCENT2}" stroke-opacity=".7"/>
      <text x="28" y="32" text-anchor="middle" font-family="{MONO}" font-size="9.5" font-weight="600" fill="{ACCENT2}">&gt;_</text>
      <text x="50" y="26" font-size="13" font-weight="600" fill="#F4F4FF">Deep</text>
      <text x="50" y="41" font-size="10.5" fill="{SOFT}">AI agent</text>
      <circle cx="98" cy="37.5" r="2.6" fill="#4ADE9B"><animate attributeName="opacity" values="1;.35;1" dur="2.4s" repeatCount="indefinite"/></circle>
      <rect x="0" y="56" width="332" height="1" fill="url(#hair)"/>
      <g opacity="0"><animate attributeName="opacity" values="0;0;1;1;0" keyTimes="0;.05;.1;.93;1" dur="10s" repeatCount="indefinite"/>
        <rect x="132" y="72" width="184" height="30" rx="15" fill="{ACCENT}" fill-opacity=".9"/>
        <text x="224" y="91.5" text-anchor="middle" font-size="12" font-weight="500" fill="#fff">What does Lake B2B do?</text></g>
      <g opacity="0"><animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;.14;.17;.3;.33;1" dur="10s" repeatCount="indefinite"/>
        <rect x="16" y="116" width="58" height="28" rx="14" fill="#fff" fill-opacity=".08"/>
        <circle cx="33" cy="130" r="2.8" fill="#fff"><animate attributeName="opacity" values=".25;1;.25" dur="1.1s" repeatCount="indefinite"/></circle>
        <circle cx="45" cy="130" r="2.8" fill="#fff"><animate attributeName="opacity" values=".25;1;.25" dur="1.1s" begin=".2s" repeatCount="indefinite"/></circle>
        <circle cx="57" cy="130" r="2.8" fill="#fff"><animate attributeName="opacity" values=".25;1;.25" dur="1.1s" begin=".4s" repeatCount="indefinite"/></circle></g>
      <g opacity="0"><animate attributeName="opacity" values="0;0;1;1;0" keyTimes="0;.32;.34;.93;1" dur="10s" repeatCount="indefinite"/>
        <rect x="16" y="116" width="250" height="88" rx="14" fill="#fff" fill-opacity=".07"/>
        <rect x="30" y="132" height="6" rx="3" fill="#E9E8FF" fill-opacity=".8" width="0"><animate attributeName="width" values="0;0;214;214;0" keyTimes="0;.34;.42;.93;1" dur="10s" repeatCount="indefinite"/></rect>
        <rect x="30" y="148" height="6" rx="3" fill="#E9E8FF" fill-opacity=".8" width="0"><animate attributeName="width" values="0;0;196;196;0" keyTimes="0;.42;.5;.93;1" dur="10s" repeatCount="indefinite"/></rect>
        <rect x="30" y="164" height="6" rx="3" fill="#E9E8FF" fill-opacity=".8" width="0"><animate attributeName="width" values="0;0;220;220;0" keyTimes="0;.5;.58;.93;1" dur="10s" repeatCount="indefinite"/></rect>
        <rect x="30" y="180" height="6" rx="3" fill="#E9E8FF" fill-opacity=".8" width="0"><animate attributeName="width" values="0;0;124;124;0" keyTimes="0;.58;.64;.93;1" dur="10s" repeatCount="indefinite"/></rect></g>
      <g opacity="0" font-size="10" font-weight="500" fill="{SOFT}"><animate attributeName="opacity" values="0;0;1;1;0" keyTimes="0;.68;.72;.93;1" dur="10s" repeatCount="indefinite"/>
        <rect x="16" y="214" width="112" height="20" rx="10" fill="none" stroke="#fff" stroke-opacity=".18"/><text x="72" y="227.5" text-anchor="middle">1 · deependhq.com</text>
        <rect x="134" y="214" width="96" height="20" rx="10" fill="none" stroke="#fff" stroke-opacity=".18"/><text x="182" y="227.5" text-anchor="middle">2 · lakeb2b.com</text></g>
    </g></g>'''
write("header.svg", frame(W, H, body, "ask deep: the AI messenger that answers with sources, books calls and keeps the news fresh"))

# ------------------------------------------------------------------ meta: stack and quality on one quiet strip
W, H = 1200, 76
stack = ["Python 3.11", "FastAPI", "Postgres 16 · pgvector", "Web Component", "Docker"]
quality = [("682", "tests"), ("43/43", "real questions"), ("all", "browser checks")]
# one text run per side: the viewer's own font measures the spacing, so it is even whatever font they have
sep = f'<tspan fill="{ACCENT}" font-weight="700">   ·   </tspan>'
body = (f'    <text x="36" y="44" xml:space="preserve" font-size="13" font-weight="500" fill="#E6E7F8">'
        + sep.join(e(s) for s in stack) + '</text>\n')
body += f'    <rect x="{W / 2 + 64}" y="22" width="1" height="32" fill="#fff" fill-opacity=".12"/>\n'
dot = f'<tspan fill="#4ADE9B" font-size="15">●<animate attributeName="fill-opacity" values="1;.35;1" dur="2.8s" repeatCount="indefinite"/></tspan>'
body += (f'    <text x="{W - 36}" y="44" xml:space="preserve" text-anchor="end" font-size="12.5" fill="{SOFT}">'
         + "     ".join(f'{dot}  <tspan font-size="14" font-weight="600" fill="#F4F4FF">{e(n)}</tspan>  {e(label)}' for n, label in quality)
         + '</text>\n')
write("meta.svg", frame(W, H, body, "Python 3.11, FastAPI, Postgres 16 with pgvector, a web component, Docker; 682 tests, 43 of 43 real questions, all browser checks passing"))

# ------------------------------------------------------------------ features
W, H = 1200, 700
feats = [("chat", "Answers with sources", "Every answer cites its pages;", "a polite refusal, never a guess"),
         ("globe", "Every company site", "LakeB2B and SPAN, fresh every 6 h,", "searched live when something is new"),
         ("calendar", "Booking in the chat", "Call type, date, time, confirm;", "guests, a Zoom link, a calendar invite"),
         ("news", "News, like Intercom", "A featured story, a row per feed,", "articles and reactions inside"),
         ("bolt", "News that checks itself", "Sooner after a change, rarer when", "quiet; edits and removals followed"),
         ("compass", "Help center", "Collections and articles, searched", "by meaning, written from the site"),
         ("clipboard", "Pre-call brief", "Who they are, what they read, and", "a lead score with a reason per point"),
         ("users", "Team replies in the chat", "Answer from the console; it lands", "in the visitor's chat or inbox"),
         ("trend", "Learns every day", "Unanswered questions become answers;", "call outcomes re-weight the score"),
         ("mic", "Voice, any language", "A mic button and hands-free calls,", "answers in the visitor's language"),
         ("bell", "Tells you when it breaks", "Model, credit, database, email and", "news checks, with an alert email"),
         ("shield", "Safe and hard to lose", "Rate limits, a spend cap, signed links,", "nightly backups, a saved email queue")]
TW, TH, GX, GY, X0, Y0 = 364, 120, 20, 18, 36, 124
body = heading(W / 2, 54, "CAPABILITIES", "Everything visitors and the team need, in one messenger", "middle")
for i, (ic, title, l1, l2) in enumerate(feats):
    c, r = i % 3, i // 3
    x, y = X0 + c * (TW + GX), Y0 + r * (TH + GY)
    body += f'''    <g opacity="0">{fade_in(.15 + i * .07)}
      <rect x="{x}" y="{y}" width="{TW}" height="{TH}" rx="16" fill="url(#card)" stroke="#fff" stroke-opacity=".09"/>
      <rect x="{x}" y="{y}" width="{TW}" height="{TH}" rx="16" fill="none" stroke="{ACCENT2}" stroke-width="1.2"><animate attributeName="stroke-opacity" {spotlight(i, 12, 24, "0", ".75")}/></rect>
      <rect x="{x + 24}" y="{y + 26}" width="44" height="44" rx="12" fill="{ACCENT}" fill-opacity=".1" stroke="{ACCENT2}" stroke-opacity=".28"><animate attributeName="fill-opacity" {spotlight(i, 12, 24, ".1", ".32")}/></rect>
      {icon(ic, x + 46, y + 48, 22)}
      <text x="{x + 88}" y="{y + 45}" font-size="16" font-weight="600" letter-spacing="-.2" fill="#F4F4FF">{e(title)}</text>
      <text x="{x + 88}" y="{y + 70}" font-size="12.8" fill="{SOFT}">{e(l1)}</text>
      <text x="{x + 88}" y="{y + 89}" font-size="12.8" fill="{SOFT}">{e(l2)}</text>
    </g>
'''
write("features.svg", frame(W, H, body, "Capabilities: answers with sources, every company site, booking, news, help center, "
                                        "pre-call briefs, team replies, learning, voice, alerts and safety"))

# ------------------------------------------------------------------ backend map
W, H = 1200, 840
CW, CH, GAP, TOP = 316, 112, 16, 140
CX, CY, CR = 600, 478, 70
modules = [
    ("chat", "Answering", "chat.py", ["Small talk and follow-up rewrites", "Hybrid search over every site", "Citations, refusals, backup model"]),
    ("book", "Knowledge", "sites.py", ["deependhq.com re-read nightly", "Company sites indexed every 6 h", "Live WordPress search on demand"]),
    ("news", "News engine", "news.py", ["Adaptive checks, 15 min to 24 h", "Only real changes, removals followed", "Feeds, articles and reactions"]),
    ("calendar", "Booking", "booking/", ["Zoom API, public page, browser worker", "Reschedule and cancel anywhere", "Branded emails, .ics, reminders"]),
    ("mic", "Voice & media", "media.py", ["Whisper or browser speech", "Spoken answers, hands-free calls", "Attachments read, never obeyed"]),
    ("target", "Leads & intelligence", "precall.py", ["Channel, UTM, IP and network owner", "Evidence-based lead score", "Pre-call brief, hot-lead alerts"]),
    ("layers", "Memory & learning", "gaps.py", ["Per-chat and cross-visit memory", "Gaps become approved answers", "Call outcomes re-weight the score"]),
    ("users", "Team & console", "team.py", ["Replies land in the visitor's chat", "Status, ratings, outreach rules", "News and help center moderation"]),
    ("pulse", "Reliability", "health.py", ["Health checks with alert emails", "Nightly backups, saved email queue", "One scheduler across instances"]),
    ("shield", "Security & privacy", "security/", ["CORS, rate limits, spend cap", "Signed links, HMAC or Clerk identity", "Sanitised HTML, retention purges"]),
]
N, CYCLE = len(modules), 20
body = heading(W / 2, 56, "ARCHITECTURE", "One FastAPI process, Postgres with pgvector, no queue server", "middle")
links, cards, dots = [], [], []
for i, (ic, title, files, lines) in enumerate(modules):
    left, row = i < 5, i % 5
    x = 36 if left else W - 36 - CW
    y = TOP + row * (CH + GAP)
    cy = y + CH / 2
    x1, x2 = (x + CW, CX - CR) if left else (x, CX + CR)
    bend = 110 if left else -110
    d = f"M{x1} {cy:.0f} C {x1 + bend} {cy:.0f}, {x2 - bend * .6:.0f} {CY}, {x2} {CY}"
    links.append(f'''    <path d="{d}" fill="none" stroke="#fff" stroke-opacity=".08" stroke-width="1.2"/>
    <path d="{d}" fill="none" stroke="url(#edge)" stroke-width="1.4" stroke-dasharray="2 10" stroke-linecap="round">
      <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="1.6s" repeatCount="indefinite"/>
      <animate attributeName="stroke-opacity" {spotlight(i, N, CYCLE, ".18", ".8")}/></path>''')
    dur = 3.4 + (i % 3) * .5
    dots.append(f'''    <circle r="3" fill="#fff" filter="url(#soft)" opacity=".8"><animateMotion dur="{dur:.1f}s" begin="{i * .41:.2f}s" repeatCount="indefinite" path="{d}"/></circle>
    <circle r="1.7" fill="#fff"><animateMotion dur="{dur:.1f}s" begin="{i * .41:.2f}s" repeatCount="indefinite" path="{d}"/></circle>''')
    bullets = "\n".join(f'      <circle cx="{x + 25}" cy="{y + 64 + k * 17}" r="1.8" fill="{ACCENT2}" fill-opacity=".8"/>'
                        f'<text x="{x + 35}" y="{y + 68 + k * 17}" font-size="12.3" fill="{SOFT}">{e(t)}</text>' for k, t in enumerate(lines))
    cards.append(f'''    <g opacity="0">{fade_in(.25 + row * .12 + (0 if left else .06), -16 if left else 16, 0)}
      <rect x="{x}" y="{y}" width="{CW}" height="{CH}" rx="14" fill="url(#card)" stroke="#fff" stroke-opacity=".09"/>
      <rect x="{x}" y="{y}" width="{CW}" height="{CH}" rx="14" fill="none" stroke="{ACCENT2}" stroke-width="1.2"><animate attributeName="stroke-opacity" {spotlight(i, N, CYCLE, "0", ".7")}/></rect>
      {icon(ic, x + 30, y + 31, 18)}
      <text x="{x + 50}" y="{y + 36}" font-size="15" font-weight="600" letter-spacing="-.2" fill="#F4F4FF">{e(title)}</text>
      <text x="{x + CW - 18}" y="{y + 35}" text-anchor="end" font-family="{MONO}" font-size="10.5" fill="{ACCENT2}" fill-opacity=".85">{e(files)}</text>
      <rect x="{x + 18}" y="{y + 48}" width="{CW - 36}" height="1" fill="url(#hair)"/>
{bullets}
    </g>''')
core = f'''    <circle cx="{CX}" cy="{CY}" r="{CR}" fill="none" stroke="{ACCENT2}" stroke-width="1.2">
      <animate attributeName="r" values="{CR};{CR + 56}" dur="4s" repeatCount="indefinite"/><animate attributeName="stroke-opacity" values=".55;0" dur="4s" repeatCount="indefinite"/></circle>
    <circle cx="{CX}" cy="{CY}" r="{CR}" fill="none" stroke="#6FA8FF" stroke-width="1">
      <animate attributeName="r" values="{CR};{CR + 56}" dur="4s" begin="2s" repeatCount="indefinite"/><animate attributeName="stroke-opacity" values=".4;0" dur="4s" begin="2s" repeatCount="indefinite"/></circle>
    <circle cx="{CX}" cy="{CY}" r="{CR + 13}" fill="none" stroke="#fff" stroke-opacity=".22" stroke-dasharray="1.5 9">
      <animateTransform attributeName="transform" type="rotate" from="0 {CX} {CY}" to="360 {CX} {CY}" dur="40s" repeatCount="indefinite"/></circle>
    <circle cx="{CX}" cy="{CY}" r="{CR}" fill="url(#core)"/>
    <circle cx="{CX}" cy="{CY}" r="{CR - .5}" fill="none" stroke="#fff" stroke-opacity=".22"/>
    <text x="{CX}" y="{CY - 4}" text-anchor="middle" font-size="20" font-weight="600" letter-spacing="-.4" fill="#fff">ask deep</text>
    <text x="{CX}" y="{CY + 19}" text-anchor="middle" font-family="{MONO}" font-size="12.5" fill="#E3DEFF">FastAPI</text>'''
ends = f'''    <path d="M{CX} {CY - CR - 8} V 258" stroke="#fff" stroke-opacity=".22" stroke-dasharray="2 6"><animate attributeName="stroke-dashoffset" from="0" to="16" dur="1.4s" repeatCount="indefinite"/></path>
    {chip(CX - 124, 220, 248, 38, 19)}
    {icon("chat", CX - 96, 239, 16)}
    <text x="{CX - 78}" y="244" font-size="12.5" font-weight="500" fill="#E6E7F8">&lt;deep-assistant&gt; · SSE</text>
    <path d="M{CX} {CY + CR + 8} V 660" stroke="#fff" stroke-opacity=".22" stroke-dasharray="2 6"><animate attributeName="stroke-dashoffset" from="0" to="-16" dur="1.4s" repeatCount="indefinite"/></path>
    {chip(CX - 124, 662, 248, 38, 19)}
    {icon("database", CX - 96, 681, 16)}
    <text x="{CX - 78}" y="686" font-size="12.5" font-weight="500" fill="#E6E7F8">Postgres 16 · pgvector</text>
    <g font-size="12" fill="{SOFT}" text-anchor="middle">
      <text x="{CX}" y="748"><tspan fill="#F4F4FF" font-weight="600">127</tspan> endpoints   ·   <tspan fill="#F4F4FF" font-weight="600">21</tspan> scheduled jobs</text>
      <text x="{CX}" y="770"><tspan fill="#F4F4FF" font-weight="600">35</tspan> tables   ·   <tspan fill="#F4F4FF" font-weight="600">60+</tspan> modules</text>
    </g>'''
write("backend.svg", frame(W, H, body + "\n".join(links) + "\n" + "\n".join(dots) + "\n" + core + "\n" + ends + "\n" + "\n".join(cards),
                           "Architecture: a FastAPI core with ten modules: answering, knowledge, news, booking, voice, leads, "
                           "memory and learning, team, reliability, security"))

# ------------------------------------------------------------------ pipeline
W, H = 1200, 340
steps = [("chat", "Understand", ["Small talk, follow-ups,", "the visitor's language"]),
         ("search", "Search", ["deependhq.com, company", "sites, help articles"]),
         ("globe", "Look further", ["Live search on the", "company's own site"]),
         ("spark", "Answer", ["Only from the sources,", "every claim cited"]),
         ("send", "Act", ["Book, reschedule, or", "hand over to the team"])]
xs, LY, DUR = [150, 375, 600, 825, 1050], 186, 9
span = xs[-1] - xs[0]
body = heading(64, 56, "ONE QUESTION", "From a visitor's words to a cited answer")
body += f'''    <line x1="{xs[0]}" y1="{LY}" x2="{xs[-1]}" y2="{LY}" stroke="#fff" stroke-opacity=".1" stroke-width="2"/>
    <line x1="{xs[0]}" y1="{LY}" x2="{xs[-1]}" y2="{LY}" stroke="url(#edge)" stroke-width="2" stroke-dasharray="{span}" stroke-dashoffset="{span}">
      <animate attributeName="stroke-dashoffset" values="{span};0;0;{span}" keyTimes="0;.8;.95;1" dur="{DUR}s" repeatCount="indefinite"/></line>
    <circle r="7" fill="#fff" filter="url(#soft)"><animateMotion path="M{xs[0]} {LY} H {xs[-1]}" keyPoints="0;1;1" keyTimes="0;.8;1" calcMode="linear" dur="{DUR}s" repeatCount="indefinite"/></circle>
    <circle r="3.4" fill="#fff"><animateMotion path="M{xs[0]} {LY} H {xs[-1]}" keyPoints="0;1;1" keyTimes="0;.8;1" calcMode="linear" dur="{DUR}s" repeatCount="indefinite"/></circle>
'''
for i, (ic, title, lines) in enumerate(steps):
    x, at = xs[i], .8 * i / 4
    on = f'values="0;0;1;1;0" keyTimes="0;{max(0, at - .01):.3f};{at + .03:.3f};.95;1" dur="{DUR}s" repeatCount="indefinite"'
    body += f'''    <g opacity="0">{fade_in(.2 + i * .14)}
      <circle cx="{x}" cy="{LY}" r="32" fill="{INK}" stroke="#fff" stroke-opacity=".16"/>
      <circle cx="{x}" cy="{LY}" r="32" fill="url(#core)" opacity="0"><animate attributeName="opacity" {on}/></circle>
      <circle cx="{x}" cy="{LY}" r="32" fill="none" stroke="{ACCENT2}" stroke-width="1.2" opacity="0"><animate attributeName="opacity" {on}/>
        <animate attributeName="r" values="32;32;48;48" keyTimes="0;{at:.3f};{min(.99, at + .14):.3f};1" dur="{DUR}s" repeatCount="indefinite"/>
        <animate attributeName="stroke-opacity" values="0;0;.7;0;0" keyTimes="0;{at:.3f};{at + .01:.3f};{min(.99, at + .14):.3f};1" dur="{DUR}s" repeatCount="indefinite"/></circle>
      {icon(ic, x, LY, 22, "#EDEBFF")}
      <text x="{x}" y="{LY - 52}" text-anchor="middle" font-family="{MONO}" font-size="11" fill="{ACCENT2}" fill-opacity=".85">0{i + 1}</text>
      <text x="{x}" y="{LY + 64}" text-anchor="middle" font-size="16" font-weight="600" letter-spacing="-.2" fill="#F4F4FF">{e(title)}</text>
      <text x="{x}" y="{LY + 87}" text-anchor="middle" font-size="12.5" fill="{SOFT}">{e(lines[0])}</text>
      <text x="{x}" y="{LY + 104}" text-anchor="middle" font-size="12.5" fill="{SOFT}">{e(lines[1])}</text>
    </g>
'''
write("pipeline.svg", frame(W, H, body, "One question: understand, search, look further, answer, act"))

# ------------------------------------------------------------------ news loop
W, H = 1200, 480
RX, RY, OX, OY = 360, 136, 600, 286
stages = [("clock", "Tick", "every 5 minutes"), ("target", "Due?", "only sources whose time came"),
          ("download", "Fetch", "ETag, 304, same bytes skipped"), ("code", "Parse", "RSS, sitemaps, YouTube, Bing"),
          ("save", "Save", "only real changes, removals"), ("refresh", "Refresh", "the widget re-asks every 2 min")]
path = f"M{OX} {OY - RY} A {RX} {RY} 0 1 1 {OX - .01} {OY - RY}"
body = heading(64, 56, "NEWS", "Checked again soon after a site changes, less often while it is quiet")
body += f'''    <ellipse cx="{OX}" cy="{OY}" rx="{RX}" ry="{RY}" fill="none" stroke="#fff" stroke-opacity=".08" stroke-width="1.5"/>
    <ellipse cx="{OX}" cy="{OY}" rx="{RX}" ry="{RY}" fill="none" stroke="url(#edge)" stroke-width="1.3" stroke-dasharray="2 10" stroke-opacity=".65">
      <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="1.8s" repeatCount="indefinite"/></ellipse>
    <circle r="8" fill="#fff" filter="url(#soft)"><animateMotion path="{path}" dur="12s" repeatCount="indefinite"/></circle>
    <circle r="3.6" fill="#fff"><animateMotion path="{path}" dur="12s" repeatCount="indefinite"/></circle>
    <g text-anchor="middle">
      <text x="{OX}" y="{OY - 16}" font-size="11.5" font-weight="600" letter-spacing="3.2" fill="{ACCENT2}">ADAPTIVE SCHEDULE</text>
      <text x="{OX}" y="{OY + 18}" font-size="30" font-weight="600" letter-spacing="-.6" fill="#F7F7FF">15 min  ⇄  24 h</text>
      <text x="{OX}" y="{OY + 44}" font-size="13" fill="{SOFT}">Sooner after a change, 1.5× later while quiet, backing off on errors</text>
    </g>
'''
for i, (ic, title, sub) in enumerate(stages):
    ang = -math.pi / 2 + 2 * math.pi * i / len(stages)
    x, y = OX + RX * math.cos(ang), OY + RY * math.sin(ang)
    at, w = i / len(stages), 214
    glow = f'values="0;0;1;0;0" keyTimes="0;{max(0, at - .001):.3f};{at + .04:.3f};{min(.999, at + .15):.3f};1" dur="12s" repeatCount="indefinite"'
    body += f'''    <g opacity="0">{fade_in(.2 + i * .14)}
      <rect x="{x - w / 2:.0f}" y="{y - 29:.0f}" width="{w}" height="58" rx="14" fill="{INK}" stroke="#fff" stroke-opacity=".12"/>
      <rect x="{x - w / 2:.0f}" y="{y - 29:.0f}" width="{w}" height="58" rx="14" fill="{ACCENT}" fill-opacity=".14" stroke="{ACCENT2}" stroke-opacity=".6" opacity="0"><animate attributeName="opacity" {glow}/></rect>
      {icon(ic, x - w / 2 + 28, y, 18)}
      <text x="{x - w / 2 + 50:.0f}" y="{y - 3:.0f}" font-size="14.5" font-weight="600" fill="#F4F4FF">{e(title)}</text>
      <text x="{x - w / 2 + 50:.0f}" y="{y + 15:.0f}" font-size="11" fill="{SOFT}">{e(sub)}</text>
    </g>
'''
write("newsloop.svg", frame(W, H, body, "News: tick, due, fetch, parse, save, refresh; checked every 15 minutes to 24 hours"))

# ------------------------------------------------------------------ jobs: four lanes
W, H = 1200, 430
lanes = [("CONTINUOUS", [("news_tick", "5 min"), ("outbox_recover", "5 min"), ("health", "10 min"), ("zoom_link_backfill", "10 min"),
                         ("geo_retry", "10 min"), ("gap_followups", "15 min"), ("team_reply_emails", "1 min")]),
         ("HOURLY", [("outcome_asks", ":05"), ("nudges", ":15"), ("hot_leads", ":30"), ("reminders", ":45"), ("kb_sites", "6 h")]),
         ("NIGHTLY", [("recrawl", "02:30"), ("tracking_purge", "03:10"), ("gap_drafts", "03:20"), ("memory_purge", "03:25"),
                      ("email_ask_purge", "03:30"), ("score_learning", "03:40"), ("db_backup", "03:50")]),
         ("WEEKLY", [("weekly_digest", "Mon 09:00"), ("geoip_update", "Wed 04:50")])]
LX, X0, XMAX, ROW0, LINE, LANEGAP = 64, 214, 1164, 132, 46, 22
# lay the chips out first (a lane wraps onto a second line when it runs out of room), then size the picture
placed, y = [], ROW0
for lane, jobs in lanes:
    x, top = X0, y
    for name, when in jobs:
        w = len(name) * 7.1 + len(when) * 6.6 + 40
        if x + w > XMAX:
            x, y = X0, y + LINE
        placed.append((name, when, x, y, w))
        x += w + 10
    placed.append((lane, None, top, y, 0))
    y += LINE + LANEGAP
H = y + 24
body = heading(64, 56, "SCHEDULED JOBS", "Twenty-one jobs, all in-process, one runner across instances")
body += f'''    <rect x="190" y="{ROW0 - 14}" width="1.5" height="{y - ROW0 - LANEGAP - 4}" fill="url(#edge)" opacity=".45"/>
    <g><animateTransform attributeName="transform" type="translate" values="0 0;950 0;0 0" dur="18s" repeatCount="indefinite"/>
      <rect x="{X0}" y="{ROW0 - 18}" width="1.5" height="{y - ROW0 - LANEGAP + 4}" fill="{ACCENT2}" opacity=".5"/>
      <rect x="{X0 - 8}" y="{ROW0 - 18}" width="17" height="{y - ROW0 - LANEGAP + 4}" fill="{ACCENT2}" opacity=".08" filter="url(#soft)"/></g>
'''
k = 0
for name, when, x, yy, w in placed:
    if when is None:                       # the lane's label, at its first line
        body += f'    <text x="{LX}" y="{x + 12}" font-size="11" font-weight="600" letter-spacing="2.6" fill="{SOFT}">{name}</text>\n'
        body += f'    <circle cx="190.8" cy="{x + 8}" r="4" fill="{INK}" stroke="{ACCENT2}" stroke-width="1.3"/>\n'
        continue
    body += f'''    <g opacity="0">{fade_in(.2 + k * .05, 0, 6, .6)}
      <rect x="{x:.0f}" y="{yy - 9}" width="{w:.0f}" height="34" rx="9" fill="#fff" fill-opacity=".045" stroke="#fff" stroke-opacity=".1"/>
      <text x="{x + 13:.0f}" y="{yy + 12}" font-family="{MONO}" font-size="11.5" fill="#E6E7F8">{e(name)}</text>
      <text x="{x + w - 13:.0f}" y="{yy + 12}" text-anchor="end" font-size="11.5" font-weight="600" fill="{ACCENT2}">{e(when)}</text>
    </g>
'''
    k += 1
body += f'    <text x="{LX}" y="{H - 30}" font-size="11.5" fill="{SOFT}" fill-opacity=".8">Times in the host timezone (Asia/Kolkata). With NEWS_DYNAMIC=false, news_tick becomes fixed hourly and daily runs.</text>\n'
H += 6
write("jobs.svg", frame(W, H, body, "Scheduled jobs: continuous, hourly, nightly and weekly"))
print("jobs.svg height", H)

# ------------------------------------------------------------------ divider
write("divider.svg", f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 24" width="1200" height="24" role="img" aria-label="">
  <defs>
    <linearGradient id="l" x1="0" x2="1"><stop offset="0" stop-color="{ACCENT}" stop-opacity="0"/><stop offset=".5" stop-color="{ACCENT}" stop-opacity=".55"/><stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></linearGradient>
    <radialGradient id="d"><stop offset="0" stop-color="{ACCENT2}" stop-opacity=".9"/><stop offset="1" stop-color="{ACCENT2}" stop-opacity="0"/></radialGradient>
  </defs>
  <rect x="120" y="11.5" width="960" height="1" fill="url(#l)"/>
  <circle cy="12" r="7" fill="url(#d)"><animate attributeName="cx" values="300;900;300" dur="12s" repeatCount="indefinite"/></circle>
</svg>
''')
# ------------------------------------------------------------------ footer: transparent, readable on light and dark pages
write("footer.svg", f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 96" width="1200" height="96" role="img" aria-label="ask deep, built for Champions Group">
  <title>ask deep, built for Champions Group</title>
  <defs>
    <linearGradient id="l" x1="0" x2="1"><stop offset="0" stop-color="{ACCENT}" stop-opacity="0"/><stop offset=".5" stop-color="{ACCENT}" stop-opacity=".6"/><stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></linearGradient>
    <radialGradient id="d"><stop offset="0" stop-color="{ACCENT2}"/><stop offset="1" stop-color="{ACCENT2}" stop-opacity="0"/></radialGradient>
  </defs>
  <rect x="200" y="22" width="800" height="1" fill="url(#l)"/>
  <circle cy="22.5" r="8" fill="url(#d)"><animate attributeName="cx" values="360;840;360" dur="14s" repeatCount="indefinite"/></circle>
  <g font-family="{SANS}" text-anchor="middle">
    <text x="600" y="58" font-family="{MONO}" font-size="15" font-weight="600" fill="{ACCENT}">ask deep <tspan fill-opacity=".7">&gt;_</tspan></text>
    <text x="600" y="82" xml:space="preserve" font-size="11" font-weight="600" letter-spacing="3" fill="#8C90B8">BUILT FOR CHAMPIONS GROUP   ·   DEEPENDHQ.COM   ·   PRIVATE AND PROPRIETARY</text>
  </g>
</svg>
''')
print("header, meta, features, backend, pipeline, newsloop, jobs, divider, footer ->", OUT)
