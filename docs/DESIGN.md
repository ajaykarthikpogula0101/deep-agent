# DESIGN.md — "Electron Scan" (the Ask Deep chat)

Applies to `static/chat.html` (the chat page, also loaded in the widget iframe) and the launcher in
`static/widget.js`. The host site deependhq.com keeps its own look; this spec is only for the assistant surface.
Replaces the earlier pixel-lace spec.

## 1. Visual theme & atmosphere

A **precision instrument**, not a retro screen. The reference is a modern scanning-electron-microscope console:
graphite surfaces tinted toward green, a restrained scan-green for labels, reticle brackets and status, orange for
the one primary action (the beam), and a barely-there scanline texture over the whole surface. Readouts in the header
show real values (source, timezone, session, status), never decoration. Calm, exact, executive-grade; nothing blinks
except the scan bar while an answer is being generated.

## 2. Color palette & roles

| Token | Dark (default) | Light | Role |
|---|---|---|---|
| `--bg` | `#0e1311` | `#f2f5f1` | page ground |
| `--panel` | `#141b18` | `#fbfcfa` | header, composer, bot bubble, tags |
| `--panel-2` | `#1b2420` | `#e9eeea` | visitor bubble, hover fills |
| `--line` / `--line-strong` | `#27332d` / `#3a4a41` | `#d3dcd5` / `#aebbb2` | hairlines, borders |
| `--text` | `#e6ece8` | `#182019` | body text |
| `--muted` | `#9aa8a0` | `#5c6b62` | secondary text, readouts |
| `--scan` | `#8fd3a3` | `#257a4d` | reticle brackets, labels, "ready" status, focus rings |
| `--beam` | `#f28c28` | `#f28c28` | primary buttons only (dark text `#1a1208` on it) |
| `--beam-text` | `#f6a94f` | `#a94c12` | links, "scanning" status |
| `--danger` | `#e8907f` | `#b4452f` | offline, slot taken, stop |

Ratio: ~60% ground and panels, ~30% text and hairlines, ~10% scan-green and orange combined. Neutrals carry a
green tint. Never `#000`/`#fff`, no gradients, no glows, no glass. Light mode is a printed-micrograph paper, not an
inversion.

## 3. Typography

| Role | Face | Size / weight |
|---|---|---|
| Body, bubbles, buttons, select | **IBM Plex Sans** | 16 px / 1.55, 400; 600 for primary buttons |
| Readouts, labels, tools, hint line | **IBM Plex Mono** (`.mono`) | 11 px, uppercase, .06em tracking |
| Title | IBM Plex Sans 600 with the `deep >_` mark in Plex Mono 500 | 16 px |

Max measure is the bubble (88% of the column, 80% from 640 px). Monospace is used only for instrument-style
readouts and labels, never for running text.

## 4. Component stylings

- **Bubble** `.msg`: 1 px hairline, 12×16 px padding, panel fill, and **reticle brackets**: a 10×1 and 1×10 scan-green
  line in each corner drawn with eight background gradients. Visitor bubbles use panel-2 with a stronger hairline and
  no brackets. A mono meta line above each shows who and the time.
- **Generating**: a 1 px scan-green line sweeps inside the bubble; the 2 px scan bar under the header sweeps too;
  status reads "scanning". Both stop under reduced motion.
- **Buttons** `.btn`: 44 px min height, 4 px radius, hairline border that turns scan-green on hover. `.primary` is
  the beam: orange fill, dark text, 600 weight. Used for send, choose call, confirm on Zoom. Slots are secondary.
- **Message tools** (copy, retry): 32 px ghost buttons in mono under each answer, dimmed until hover or focus.
- **Sources**: tag row prefixed "from", each tag a hairline chip with a 6 px scan-green square.
- **Picker**: native select on ground colour with a chevron drawn from two borders; slides down via grid rows.
- **Suggestion chips**: pill outlines in the empty state; removed on first send.
- **Composer**: auto-growing textarea (1 to 5 lines), 44 px square send button that becomes a stop button while
  generating; hint line "Enter to send · Shift+Enter for a new line · Esc to stop"; character count past 1200.
- **Header actions**: 40 px icon buttons (theme, download transcript, new conversation) with inline SVG, aria-labels
  and titles.
- **Jump to latest**: floating pill above the composer, visible only when scrolled up.
- **Launcher** (host site): 56 px graphite square, scan-green hairline, orange label, system monospace.

## 5. Layout principles

Single column, mobile first. Header bar 12/16 px, readouts row wraps, log 20/16 px, composer 10/16 px plus safe
area; all step up at 640 px. Gaps: 18 px between rows, 10 px between buttons, 6 px between tags. Asymmetry comes from
the alignment of visitor rows to the right and the tools row hanging under answers.

## 6. Depth & elevation

Flat surfaces separated by hairlines. One soft shadow exists, on the floating "latest" pill and the embedded panel.
The scanline overlay (`body::after`, 1 px every 3 px at 10% black in dark, 2.5% in light) is the only texture.

## 7. Do's and don'ts

- Do keep scan-green for structure and status only; it is never a fill behind text.
- Do show real values in the readouts; if a value is unknown, show "—", never a fake number.
- Don't add emoji, gradients, glows, glass, coloured side stripes or rounded icon tiles.
- Don't animate anything but the scan bar, the in-bubble sweep and the 250 ms row entrance.
- Don't use the beam orange for more than one action per view.

## 8. Responsive behavior & device class

Device class: **pointer surface and phone** (iframe 420×640 on desktop, full screen under 768 px). Breakpoint at
640 px widens padding and narrows bubbles. Touch targets 44 px (tools 32 px, non-essential). `100dvh` and
`env(safe-area-inset-bottom)` keep the composer above home indicators. Motion budget: compositor-only transforms,
three animations, all removed under `prefers-reduced-motion`. No expressive tier.

## 9. Agent prompt guide

Quick refs: ground `#0e1311`, panel `#141b18`, text `#e6ece8`, scan `#8fd3a3`, beam `#f28c28`, link `#f6a94f`.
"Build it like an instrument console: graphite tinted green, 1 px hairlines, scan-green reticle brackets on message
corners, one orange primary action, IBM Plex Sans body with Plex Mono uppercase readouts, no gradients or glows."
Precedence: Champions Group brand skill (orange) → this file → generator defaults.
