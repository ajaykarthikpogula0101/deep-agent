# Console design (static/admin.html)

The owner's console for the ask deep assistant. One file, no build step; every element ID and the `nav button[data-pane]`
switching are unchanged, so the console's scripts work as before.

## 1. Theme and feel
A calm, data-first workspace for one owner and a small team: warm white surfaces, Champions Group orange as the only accent,
ink text. Dense where the data is (tables, tiles), generous around it. Light by default, with a real dark theme.

## 2. Colour (CSS custom properties on `:root`, dark under `:root[data-theme="dark"]`)
| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg` | #f6f4f1 | #141210 | page |
| `--panel` | #fffefc | #1c1a17 | cards, tables, inputs |
| `--panel-2` | #f3f0eb | #24211d | table headers, chips, hover |
| `--side` | #fbf9f6 | #181614 | sidebar |
| `--line` / `--line-strong` | #e7e2da / #d4cdc2 | #2f2b26 / #423c35 | borders |
| `--text` / `--ink-soft` / `--muted` | #1d1a17 / #3a352f / #6e675f | #efebe5 / #d8d2c9 / #a39b90 | text |
| `--accent` / `--accent-strong` / `--accent-soft` | #e85d17 / #c94c0e / #fdeee3 | #f2843f / #f6a46e / #3a2416 | active nav, primary buttons, links, switches |
| `--scan` | #1f7a4a | #6fcf97 | good: resolved, "in use", answered |
| `--danger` | #b4361f | #f0937f | refused, errors, delete |
| `--beam` / `--beam-text` | #f26722 / #b8470d | #f28c4a / #f6a46e | warnings, hot leads (older names kept for existing rules) |

## 3. Typography
Geist (UI) and Geist Mono (code, the digest preview). Page title 20/650, card title 15/650 with an optional quieter second
line (a card heading written "Title · explanation" is split automatically), body 14.5/1.55, table 13.5, labels 12–12.5.
Numbers use tabular figures.

## 4. Components
- **Sidebar**: brand, then Overview and three groups (Visitors, Assistant, Content), each item an outline icon + label;
  the active item is accent-tinted; News and Outreach carry count badges; the theme switch sits at the bottom.
- **Top bar**: the section's name and purpose on the left; admin token (with a lock icon), period, Load and status on the right;
  sticky, slightly translucent over scrolling content (solid where `backdrop-filter` is unsupported).
- **Tiles**: label, big number, small note; 7 per row on a laptop.
- **Cards**: 14 px radius, hairline border, faint shadow; buttons in a heading sit on its right.
- **Tables**: sticky light header, 10 px cells, hover tint on clickable rows, dates never wrap.
- **Buttons**: default (outlined), primary (accent), danger, ghost; 36 px high; visible focus ring.
- **Switches** (Knowledge, Detections): accent when on.

## 5. Layout
248 px sidebar + fluid content (max 1480 px), 32 px page padding, 20 px between cards, 12 px between tiles; 4 px base grid.

## 6. Depth
Flat: hairline borders and one faint shadow on cards and buttons; no glows, no gradients, no glass except the floating top bar.

## 7. Do and don't
Do keep one accent and let green/red carry meaning. Don't add coloured side stripes, emoji icons, gradient text or nested cards.

## 8. Responsive
Pointer surface (desktop/laptop). Under 900 px the sidebar becomes a horizontal strip above the page and the top bar
stops being sticky; tiles reflow to two columns on a phone. No motion beyond 150 ms colour transitions, all off under
`prefers-reduced-motion`.

## 9. Quick reference
Accent `#e85d17`, good `#1f7a4a`, bad `#b4361f`, ink `#1d1a17`, page `#f6f4f1`, Geist. New panes: add a `<section class="pane">`,
a sidebar button with an icon and `data-pane`, and a line in `PANE_SUB` for the top bar's description.
