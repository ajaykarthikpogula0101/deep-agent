"""Animated README diagrams, in the header's dark indigo style (pure SVG + SMIL: they animate on GitHub as <img>).

  backend.svg   the backend map: a pulsing core, ten module cards that slide in, data flowing along every line,
                and a spotlight that moves from module to module
  pipeline.svg  how one question is answered: five steps, a pulse travels the line and lights each step in turn
  newsloop.svg  how News stays fresh: a loop of six stages with a dot orbiting through them
"""
from html import escape
from pathlib import Path

OUT = str(Path(__file__).resolve().parents[1] / "docs" / "images")   # python scripts/readme_graphics.py
SANS = "'Segoe UI', Inter, -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif"
MONO = "Consolas, 'SF Mono', Menlo, 'Courier New', monospace"


def e(s):
    return escape(s, quote=True)


def frame(w, h, body, title, label=""):
    """The shared backdrop: gradient that breathes, dot grid, two drifting glows, rounded corners."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{e(title)}">
  <title>{e(title)}</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0B1033"><animate attributeName="stop-color" values="#0B1033;#10164A;#0B1033" dur="12s" repeatCount="indefinite"/></stop>
      <stop offset=".6" stop-color="#16135A"/>
      <stop offset="1" stop-color="#2A1E8C"><animate attributeName="stop-color" values="#2A1E8C;#3A2BC4;#2A1E8C" dur="12s" repeatCount="indefinite"/></stop>
    </linearGradient>
    <radialGradient id="ga"><stop offset="0" stop-color="#8B7CFF" stop-opacity=".45"/><stop offset="1" stop-color="#8B7CFF" stop-opacity="0"/></radialGradient>
    <radialGradient id="gb"><stop offset="0" stop-color="#3FA9FF" stop-opacity=".28"/><stop offset="1" stop-color="#3FA9FF" stop-opacity="0"/></radialGradient>
    <radialGradient id="core" cx=".35" cy=".3"><stop offset="0" stop-color="#8B7CFF"/><stop offset=".6" stop-color="#5546F7"/><stop offset="1" stop-color="#2A1E8C"/></radialGradient>
    <linearGradient id="card" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".11"/><stop offset="1" stop-color="#fff" stop-opacity=".05"/></linearGradient>
    <linearGradient id="edge" x1="0" x2="1"><stop offset="0" stop-color="#8B7CFF"/><stop offset="1" stop-color="#3FA9FF"/></linearGradient>
    <filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4"/></filter>
    <pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="#fff" fill-opacity=".08"/></pattern>
    <clipPath id="clip"><rect width="{w}" height="{h}" rx="26"/></clipPath>
  </defs>
  <g clip-path="url(#clip)" font-family="{SANS}">
    <rect width="{w}" height="{h}" fill="url(#bg)"/>
    <rect width="{w}" height="{h}" fill="url(#dots)"/>
    <circle cx="{w * .82}" cy="{h * .12}" r="{h * .7}" fill="url(#ga)"><animate attributeName="cx" values="{w * .82};{w * .72};{w * .82}" dur="15s" repeatCount="indefinite"/></circle>
    <circle cx="{w * .12}" cy="{h * .95}" r="{h * .6}" fill="url(#gb)"><animate attributeName="cx" values="{w * .12};{w * .24};{w * .12}" dur="17s" repeatCount="indefinite"/></circle>
{body}
  </g>
</svg>
'''


def heading(x, y, kicker, title, anchor="start"):
    return (f'    <text x="{x}" y="{y}" text-anchor="{anchor}" font-size="13" font-weight="700" letter-spacing="3" fill="#A99EFF">{e(kicker)}</text>\n'
            f'    <text x="{x}" y="{y + 30}" text-anchor="{anchor}" font-size="25" font-weight="700" fill="#fff">{e(title)}</text>\n')


def fade_in(begin, dx=0, dy=10):
    return (f'<animate attributeName="opacity" from="0" to="1" begin="{begin}s" dur=".55s" fill="freeze"/>'
            f'<animateTransform attributeName="transform" type="translate" from="{dx} {dy}" to="0 0" begin="{begin}s" dur=".55s" fill="freeze"/>')


def spotlight(i, n, dur, lo=".35", hi="1"):
    """Brightness that peaks while module i of n has the spotlight (one full cycle = dur seconds)."""
    a, b, c = i / n, (i + .5) / n, (i + 1) / n
    return f'values="{lo};{lo};{hi};{lo};{lo}" keyTimes="0;{a:.4f};{b:.4f};{c:.4f};1" dur="{dur}s" repeatCount="indefinite"'


# ------------------------------------------------------------------ backend map
W, H = 1200, 820
CW, CH, GAP, TOP = 312, 112, 16, 132
CX, CY, CR = 600, 470, 72
modules = [
    ("💬", "Answering", "chat.py", ["Small talk and follow-up rewrites", "Hybrid search over every site", "Citations, refusals, backup model"]),
    ("📚", "Knowledge", "sites.py", ["deependhq.com re-read nightly", "Company sites indexed every 6 h", "Live WordPress search on demand"]),
    ("📰", "News engine", "news.py", ["Adaptive checks, 15 min to 24 h", "Only real changes, removals followed", "Feeds, articles and reactions"]),
    ("📅", "Booking", "booking/", ["Zoom API, public page, browser worker", "Reschedule and cancel anywhere", "Branded emails, .ics, reminders"]),
    ("🎙", "Voice & media", "media.py", ["Whisper or browser speech", "Spoken answers, hands-free calls", "Attachments read, never obeyed"]),
    ("🎯", "Leads & intelligence", "precall.py", ["Channel, UTM, IP and network owner", "Evidence-based lead score", "Pre-call brief, hot-lead alerts"]),
    ("🧠", "Memory & learning", "gaps.py", ["Per-chat and cross-visit memory", "Gaps become approved answers", "Call outcomes re-weight the score"]),
    ("👥", "Team & console", "team.py", ["Replies land in the visitor's chat", "Status, ratings, outreach rules", "News and help center moderation"]),
    ("🔔", "Reliability", "health.py", ["Health checks with alert emails", "Nightly backups, saved email queue", "One scheduler across instances"]),
    ("🛡", "Security & privacy", "security/", ["CORS, rate limits, spend cap", "Signed links, HMAC or Clerk identity", "Sanitised HTML, retention purges"]),
]
N, CYCLE = len(modules), 15
body = heading(W / 2, 52, "INSIDE THE BACKEND", "One FastAPI process · Postgres + pgvector · no queue server", "middle")
links, cards, dots = [], [], []
for i, (icon, title, files, lines) in enumerate(modules):
    left = i < 5
    row = i % 5
    x = 36 if left else W - 36 - CW
    y = TOP + row * (CH + GAP)
    cy = y + CH / 2
    x1 = x + CW if left else x
    x2 = CX - CR if left else CX + CR
    bend = 110 if left else -110
    d = f"M{x1} {cy:.0f} C {x1 + bend} {cy:.0f}, {x2 - bend * .6:.0f} {CY}, {x2} {CY}"
    links.append(f'''    <path d="{d}" fill="none" stroke="url(#edge)" stroke-width="1.6" stroke-opacity=".35"/>
    <path d="{d}" fill="none" stroke="#B9B0FF" stroke-width="2" stroke-dasharray="3 9" stroke-linecap="round">
      <animate attributeName="stroke-dashoffset" from="0" to="-24" dur="1.1s" repeatCount="indefinite"/>
      <animate attributeName="stroke-opacity" {spotlight(i, N, CYCLE, ".25", ".95")}/>
    </path>''')
    dots.append(f'''    <circle r="3.6" fill="#fff" filter="url(#soft)" opacity=".9"><animateMotion dur="{2.6 + (i % 3) * .4:.1f}s" begin="{i * .37:.2f}s" repeatCount="indefinite" path="{d}"/></circle>
    <circle r="2.2" fill="#fff"><animateMotion dur="{2.6 + (i % 3) * .4:.1f}s" begin="{i * .37:.2f}s" repeatCount="indefinite" path="{d}"/></circle>''')
    begin = .25 + row * .12 + (0 if left else .06)
    bullets = "\n".join(f'        <circle cx="{x + 24}" cy="{y + 62 + k * 18}" r="2.4" fill="#8B7CFF"/><text x="{x + 34}" y="{y + 66 + k * 18}" font-size="12.5" fill="#DADDFF">{e(t)}</text>'
                        for k, t in enumerate(lines))
    cards.append(f'''    <g opacity="0">{fade_in(begin, -24 if left else 24, 0)}
      <rect x="{x}" y="{y}" width="{CW}" height="{CH}" rx="16" fill="url(#card)" stroke="#fff" stroke-opacity=".14"/>
      <rect x="{x}" y="{y}" width="{CW}" height="{CH}" rx="16" fill="none" stroke="#A99EFF" stroke-width="1.6">
        <animate attributeName="stroke-opacity" {spotlight(i, N, CYCLE, "0", ".9")}/>
      </rect>
      <rect x="{x + (0 if left else CW - 4)}" y="{y + 18}" width="4" height="{CH - 36}" rx="2" fill="url(#edge)">
        <animate attributeName="opacity" {spotlight(i, N, CYCLE, ".25", "1")}/>
      </rect>
      <text x="{x + 18}" y="{y + 33}" font-size="19">{icon}</text>
      <text x="{x + 46}" y="{y + 32}" font-size="16" font-weight="700" fill="#fff">{e(title)}</text>
      <text x="{x + CW - 16}" y="{y + 32}" text-anchor="end" font-family="{MONO}" font-size="10.5" fill="#A99EFF">{e(files)}</text>
{bullets}
    </g>''')

core = f'''    <circle cx="{CX}" cy="{CY}" r="{CR}" fill="none" stroke="#8B7CFF" stroke-width="2">
      <animate attributeName="r" values="{CR};{CR + 58}" dur="3s" repeatCount="indefinite"/>
      <animate attributeName="stroke-opacity" values=".7;0" dur="3s" repeatCount="indefinite"/>
    </circle>
    <circle cx="{CX}" cy="{CY}" r="{CR}" fill="none" stroke="#3FA9FF" stroke-width="1.5">
      <animate attributeName="r" values="{CR};{CR + 58}" dur="3s" begin="1.5s" repeatCount="indefinite"/>
      <animate attributeName="stroke-opacity" values=".55;0" dur="3s" begin="1.5s" repeatCount="indefinite"/>
    </circle>
    <circle cx="{CX}" cy="{CY}" r="{CR + 14}" fill="none" stroke="#A99EFF" stroke-opacity=".5" stroke-width="1.4" stroke-dasharray="2 10">
      <animateTransform attributeName="transform" type="rotate" from="0 {CX} {CY}" to="360 {CX} {CY}" dur="24s" repeatCount="indefinite"/>
    </circle>
    <circle cx="{CX}" cy="{CY}" r="{CR}" fill="url(#core)"/>
    <circle cx="{CX}" cy="{CY}" r="{CR - 1}" fill="none" stroke="#fff" stroke-opacity=".25"/>
    <text x="{CX}" y="{CY - 6}" text-anchor="middle" font-size="22" font-weight="800" fill="#fff">ask deep</text>
    <text x="{CX}" y="{CY + 20}" text-anchor="middle" font-family="{MONO}" font-size="15" font-weight="700" fill="#E3DEFF">&gt;_ FastAPI</text>'''

ends = f'''    <g font-size="13" font-weight="600" fill="#fff">
      <path d="M{CX} {CY - CR - 6} V 238" stroke="#A99EFF" stroke-opacity=".45" stroke-dasharray="3 6"><animate attributeName="stroke-dashoffset" from="0" to="18" dur="1s" repeatCount="indefinite"/></path>
      <rect x="{CX - 132}" y="196" width="264" height="40" rx="20" fill="#fff" fill-opacity=".1" stroke="#fff" stroke-opacity=".22"/>
      <text x="{CX}" y="221" text-anchor="middle">👤  &lt;deep-assistant&gt; widget · SSE</text>
      <path d="M{CX} {CY + CR + 6} V 640" stroke="#A99EFF" stroke-opacity=".45" stroke-dasharray="3 6"><animate attributeName="stroke-dashoffset" from="0" to="-18" dur="1s" repeatCount="indefinite"/></path>
      <rect x="{CX - 132}" y="642" width="264" height="40" rx="20" fill="#fff" fill-opacity=".1" stroke="#fff" stroke-opacity=".22"/>
      <text x="{CX}" y="667" text-anchor="middle">🐘  Postgres 16 + pgvector</text>
    </g>
    <g font-size="12.5" fill="#BFC3FF" text-anchor="middle">
      <text x="{CX}" y="726"><tspan font-weight="700" fill="#fff">127</tspan> endpoints  ·  <tspan font-weight="700" fill="#fff">21</tspan> scheduled jobs</text>
      <text x="{CX}" y="748"><tspan font-weight="700" fill="#fff">35</tspan> tables  ·  <tspan font-weight="700" fill="#fff">60+</tspan> modules</text>
    </g>'''
svg = frame(W, H, body + "\n".join(links) + "\n" + "\n".join(dots) + "\n" + core + "\n" + ends + "\n" + "\n".join(cards),
            "Inside the backend: one FastAPI process with ten modules around it")
open(f"{OUT}/backend.svg", "w", encoding="utf-8", newline="\n").write(svg)

# ------------------------------------------------------------------ pipeline: how one question is answered
W, H = 1200, 330
steps = [("💬", "Understand", ["small talk, follow-ups", "language"]),
         ("🔎", "Search", ["deependhq.com, company", "sites, help articles"]),
         ("🌐", "Look further", ["live search on the", "company's own site"]),
         ("🤖", "Answer", ["only from the sources,", "with citations"]),
         ("⚡", "Act", ["book, reschedule, hand", "over to the team"])]
xs = [150, 375, 600, 825, 1050]
LY, DUR = 178, 7.5
body = heading(64, 48, "HOW ONE QUESTION IS ANSWERED", "From a visitor's words to a cited answer, in seconds")
body += f'''    <line x1="{xs[0]}" y1="{LY}" x2="{xs[-1]}" y2="{LY}" stroke="#fff" stroke-opacity=".14" stroke-width="4" stroke-linecap="round"/>
    <line x1="{xs[0]}" y1="{LY}" x2="{xs[-1]}" y2="{LY}" stroke="url(#edge)" stroke-width="4" stroke-linecap="round" stroke-dasharray="{xs[-1] - xs[0]}" stroke-dashoffset="{xs[-1] - xs[0]}">
      <animate attributeName="stroke-dashoffset" values="{xs[-1] - xs[0]};0;0;{xs[-1] - xs[0]}" keyTimes="0;.8;.95;1" dur="{DUR}s" repeatCount="indefinite"/>
    </line>
    <circle r="9" fill="#fff" filter="url(#soft)"><animateMotion path="M{xs[0]} {LY} H {xs[-1]}" keyPoints="0;1;1" keyTimes="0;.8;1" calcMode="linear" dur="{DUR}s" repeatCount="indefinite"/></circle>
    <circle r="5" fill="#fff"><animateMotion path="M{xs[0]} {LY} H {xs[-1]}" keyPoints="0;1;1" keyTimes="0;.8;1" calcMode="linear" dur="{DUR}s" repeatCount="indefinite"/></circle>
'''
for i, (icon, title, lines) in enumerate(steps):
    x, at = xs[i], .8 * i / 4                    # when the pulse reaches this step
    on = f'values="0;0;1;1;0" keyTimes="0;{max(0, at - .01):.3f};{at + .02:.3f};.95;1" dur="{DUR}s" repeatCount="indefinite"'
    body += f'''    <g opacity="0">{fade_in(.2 + i * .15)}
      <circle cx="{x}" cy="{LY}" r="36" fill="#0B1033" stroke="#fff" stroke-opacity=".22" stroke-width="1.5"/>
      <circle cx="{x}" cy="{LY}" r="36" fill="url(#core)" opacity="0"><animate attributeName="opacity" {on}/></circle>
      <circle cx="{x}" cy="{LY}" r="36" fill="none" stroke="#A99EFF" stroke-width="2" opacity="0">
        <animate attributeName="opacity" {on}/>
        <animate attributeName="r" values="36;36;52;52" keyTimes="0;{at:.3f};{min(.99, at + .12):.3f};1" dur="{DUR}s" repeatCount="indefinite"/>
        <animate attributeName="stroke-opacity" values="0;0;.8;0;0" keyTimes="0;{at:.3f};{at + .01:.3f};{min(.99, at + .12):.3f};1" dur="{DUR}s" repeatCount="indefinite"/>
      </circle>
      <text x="{x}" y="{LY + 9}" text-anchor="middle" font-size="25">{icon}</text>
      <text x="{x - 46}" y="{LY - 52}" font-family="{MONO}" font-size="12" font-weight="700" fill="#A99EFF">0{i + 1}</text>
      <text x="{x}" y="{LY + 70}" text-anchor="middle" font-size="17" font-weight="700" fill="#fff">{e(title)}</text>
      <text x="{x}" y="{LY + 93}" text-anchor="middle" font-size="12.5" fill="#C9CCFF">{e(lines[0])}</text>
      <text x="{x}" y="{LY + 110}" text-anchor="middle" font-size="12.5" fill="#C9CCFF">{e(lines[1])}</text>
    </g>
'''
open(f"{OUT}/pipeline.svg", "w", encoding="utf-8", newline="\n").write(
    frame(W, H, body, "How one question is answered: understand, search, look further, answer, act"))

# ------------------------------------------------------------------ news loop: how News stays fresh
W, H = 1200, 470
RX, RY, OX, OY = 360, 140, 600, 270
stages = [("⏱", "Tick", "every 5 minutes"), ("🎯", "Due?", "only sources whose time came"),
          ("📡", "Fetch", "ETag · 304 · same bytes skip"), ("🧩", "Parse", "RSS · sitemaps · YouTube · Bing"),
          ("💾", "Save", "only real changes · removals"), ("🔄", "Refresh", "widget re-asks every 2 min")]
import math

body = heading(64, 48, "HOW NEWS STAYS FRESH", "Checked again soon after a site changes, less often while it's quiet")
path = f"M{OX} {OY - RY} A {RX} {RY} 0 1 1 {OX - .01} {OY - RY}"
body += f'''    <ellipse cx="{OX}" cy="{OY}" rx="{RX}" ry="{RY}" fill="none" stroke="#fff" stroke-opacity=".12" stroke-width="3"/>
    <ellipse cx="{OX}" cy="{OY}" rx="{RX}" ry="{RY}" fill="none" stroke="url(#edge)" stroke-width="2" stroke-dasharray="4 10" stroke-opacity=".7">
      <animate attributeName="stroke-dashoffset" from="0" to="-28" dur="1.2s" repeatCount="indefinite"/>
    </ellipse>
    <circle r="11" fill="#fff" filter="url(#soft)"><animateMotion path="{path}" dur="9s" repeatCount="indefinite"/></circle>
    <circle r="6" fill="#fff"><animateMotion path="{path}" dur="9s" repeatCount="indefinite"/></circle>
    <g text-anchor="middle">
      <text x="{OX}" y="{OY - 14}" font-size="15" font-weight="700" letter-spacing="2" fill="#A99EFF">ADAPTIVE SCHEDULE</text>
      <text x="{OX}" y="{OY + 20}" font-size="30" font-weight="800" fill="#fff">15 min ⇄ 24 h</text>
      <text x="{OX}" y="{OY + 46}" font-size="13.5" fill="#C9CCFF">sooner after a change · 1.5× later while quiet · backs off on errors</text>
    </g>
'''
for i, (icon, title, sub) in enumerate(stages):
    ang = -math.pi / 2 + 2 * math.pi * i / len(stages)       # clockwise from the top, like the dot
    x, y = OX + RX * math.cos(ang), OY + RY * math.sin(ang)
    at = i / len(stages)
    glow = f'values=".2;.2;1;.2;.2" keyTimes="0;{max(0, at - .001):.3f};{at + .04:.3f};{min(.999, at + .14):.3f};1" dur="9s" repeatCount="indefinite"'
    w = 210
    body += f'''    <g opacity="0">{fade_in(.2 + i * .15)}
      <rect x="{x - w / 2:.0f}" y="{y - 30:.0f}" width="{w}" height="60" rx="16" fill="#0E1240" stroke="#fff" stroke-opacity=".18"/>
      <rect x="{x - w / 2:.0f}" y="{y - 30:.0f}" width="{w}" height="60" rx="16" fill="url(#core)" opacity=".2"><animate attributeName="opacity" {glow}/></rect>
      <text x="{x - w / 2 + 22:.0f}" y="{y + 7:.0f}" font-size="20">{icon}</text>
      <text x="{x - w / 2 + 54:.0f}" y="{y - 3:.0f}" font-size="15" font-weight="700" fill="#fff">{e(title)}</text>
      <text x="{x - w / 2 + 54:.0f}" y="{y + 15:.0f}" font-size="11" fill="#D6D9FF">{e(sub)}</text>
    </g>
'''
open(f"{OUT}/newsloop.svg", "w", encoding="utf-8", newline="\n").write(
    frame(W, H, body, "How News stays fresh: tick, due, fetch, parse, save, refresh"))
print("backend.svg, pipeline.svg, newsloop.svg written")

# ------------------------------------------------------------------ features: twelve tiles, a spotlight that moves through them
W, H = 1200, 680
feats = [("💬", "Answers with sources", "Every answer cites its pages;", "a polite refusal, never a guess"),
         ("🌐", "Knows every company site", "LakeB2B and SPAN, fresh every 6 h,", "live search for anything new"),
         ("📅", "Booking in the chat", "Call type → date → time → confirm,", "guests, Zoom link, calendar invite"),
         ("📰", "News, like Intercom", "A featured story, a row per feed,", "articles and reactions inside"),
         ("⚡", "News that checks itself", "Sooner after a change, rarer when", "quiet; edits and removals followed"),
         ("🧭", "Help center", "Collections and articles, searched", "by meaning, written from the site"),
         ("📋", "Pre-call brief", "Who they are, what they read, and", "a lead score with a reason per point"),
         ("👥", "Team replies in the chat", "Answer from the console; it lands", "in the visitor's chat or inbox"),
         ("📈", "Learns every day", "Unanswered questions become answers;", "call outcomes re-weight the score"),
         ("🎙", "Voice, any language", "A mic button and hands-free calls,", "answers in the visitor's language"),
         ("🔔", "Tells you when it breaks", "Model, credit, database, email and", "news checks, with an alert email"),
         ("🛡", "Safe and hard to lose", "Rate limits, spend cap, signed links,", "nightly backups, saved email queue")]
TW, TH, GX, GY, X0, Y0 = 368, 118, 18, 16, 36, 112
body = heading(W / 2, 48, "WHAT IT DOES", "Everything visitors and the team need, in one messenger", "middle")
for i, (icon, title, l1, l2) in enumerate(feats):
    c, r = i % 3, i // 3
    x, y = X0 + c * (TW + GX), Y0 + r * (TH + GY)
    body += f'''    <g opacity="0">{fade_in(.15 + i * .08)}
      <rect x="{x}" y="{y}" width="{TW}" height="{TH}" rx="18" fill="url(#card)" stroke="#fff" stroke-opacity=".13"/>
      <rect x="{x}" y="{y}" width="{TW}" height="{TH}" rx="18" fill="url(#core)" opacity="0"><animate attributeName="opacity" {spotlight(i, 12, 18, "0", ".22")}/></rect>
      <rect x="{x}" y="{y}" width="{TW}" height="{TH}" rx="18" fill="none" stroke="#A99EFF" stroke-width="1.6"><animate attributeName="stroke-opacity" {spotlight(i, 12, 18, "0", ".95")}/></rect>
      <circle cx="{x + 46}" cy="{y + TH / 2}" r="27" fill="#0B1033" stroke="#fff" stroke-opacity=".2"/>
      <circle cx="{x + 46}" cy="{y + TH / 2}" r="27" fill="url(#core)"><animate attributeName="opacity" {spotlight(i, 12, 18, ".35", "1")}/></circle>
      <text x="{x + 46}" y="{y + TH / 2 + 8}" text-anchor="middle" font-size="22">{icon}</text>
      <text x="{x + 88}" y="{y + 44}" font-size="17" font-weight="700" fill="#fff">{e(title)}</text>
      <text x="{x + 88}" y="{y + 68}" font-size="13" fill="#D6D9FF">{e(l1)}</text>
      <text x="{x + 88}" y="{y + 87}" font-size="13" fill="#D6D9FF">{e(l2)}</text>
    </g>
'''
open(f"{OUT}/features.svg", "w", encoding="utf-8", newline="\n").write(
    frame(W, H, body, "What it does: answers with sources, company sites, booking, news, help center, briefs, team replies, learning, voice, alerts, safety"))

# ------------------------------------------------------------------ divider: a thin line with a light travelling along it
div = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 30" width="1200" height="30" role="img" aria-label="section divider">
  <defs>
    <linearGradient id="l" x1="0" x2="1"><stop offset="0" stop-color="#5546F7" stop-opacity="0"/><stop offset=".5" stop-color="#5546F7" stop-opacity=".75"/><stop offset="1" stop-color="#5546F7" stop-opacity="0"/></linearGradient>
    <radialGradient id="d"><stop offset="0" stop-color="#8B7CFF"/><stop offset="1" stop-color="#8B7CFF" stop-opacity="0"/></radialGradient>
  </defs>
  <rect x="0" y="14" width="1200" height="2" fill="url(#l)"/>
  <circle cy="15" r="9" fill="url(#d)"><animate attributeName="cx" values="120;1080;120" dur="8s" repeatCount="indefinite"/></circle>
  <circle cy="15" r="2.6" fill="#5546F7"><animate attributeName="cx" values="120;1080;120" dur="8s" repeatCount="indefinite"/></circle>
  <rect x="594" y="9" width="12" height="12" rx="2" fill="#5546F7" transform="rotate(45 600 15)"/>
</svg>
'''
open(f"{OUT}/divider.svg", "w", encoding="utf-8", newline="\n").write(div)
print("features.svg, divider.svg written")
