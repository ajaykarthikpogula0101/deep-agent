# Champ Robin Widget: DESIGN.md

Source: the colours follow deependhq.com's design system (`system.css`, identity kit v1, 1 Oct 2026: navy night `#0E1A33`, lamp marigold `#F4A62A`, paper cream `#F4EBD9`, mare grey `#A9ABA6`). Layout, type and motion are this widget's own.

## 1. Visual Theme & Atmosphere
"Navy night, marigold lamp." A calm, editorial messenger in deependhq.com's colours. Home, Messages, Settings and the conversation share one look: white surfaces with navy type, paper-cream fills and tan hairlines (the site's paper band) and marigold accents; in dark mode the site's navy night with cream type and marigold. The marigold site colour is on the launcher and the primary actions; the Champ Robin swallow is one colour (navy on light, paper cream on dark). Display type is used confidently and there is very little decoration. The widget should feel like part of deependhq.com, not like a generic SaaS chat bubble.

## 2. Color Palette & Roles
| Token | Light | Dark | Role |
|---|---|---|---|
| `--robin-primary` | `#F4A62A` marigold (configurable) | same | The site colour: launcher, primary actions (10%). Navy text on it (8.5:1) |
| `--paper` / `--surface` | `#FFFFFF` / `#FFFFFF` | `#0E1A33` / `#15213A` | Panel background / cards, bubbles, bars |
| `--sunk` | `#FBF5EA` (paper-2) | `#1C2841` (card) | Pressed and secondary fills |
| `--line` / `--line-2` | `#EAE3D5` / `#DCD2BF` | `#303C53` / `#434E64` | Hairlines / input borders |
| `--ink` / `--ink-2` / `--ink-3` | `#0E1A33` / `#3F4A5E` / `#5A6478` | `#F4EBD9` / `#A9ABA6` / `#9098AA` | Text tiers (all AA on every surface: 5.0:1 or more) |
| `--navy` | `#0E1A33` | `#F4EBD9` | Controls and titles |
| `--ai` | `#8A5A00` (marigold-ink) | `#F4A62A` | Accent text: links, labels, focus, selected states (5.9:1 / 7.9:1) |
| `--ai-mid` / `--ai-lav` / `--ai-pale` | `#F4A62A` / `#F8C877` / `#FCE6BE` | `#F4A62A` / `#795D33` / `#423B37` | Loader rings, highlights, soft fills |
| `--ai-wash` | `#FDF4E3` | marigold 12% | Hover and selected backgrounds |
| `--user-bubble` | `#F4EBD9` (paper cream) | `#1C2841` | The visitor's messages |
| `--logo` | `#0E1A33` (navy) | `#F4EBD9` (paper cream) | The swallow mark, its ring and the stage |
| `--hero` / `--hero-ink` | `#0E1A33` / `#F4EBD9` | `#0B1529` | Unread badge, call bar |
| `--ok` / `--danger` | `#26784C` / `#B42318` | `#30E060` (build) / `#F37050` | Confirmations / errors |

Surfaces stay bright white in light mode so cards and bubbles are separated by hairlines and soft navy-tinted shadows. Text on any colour is picked automatically (navy or white, black for mid colours) for WCAG contrast. A brand colour chosen in Settings takes over the accents and the swallow; when it is used as text it is darkened (light) or lightened (dark) until it reads at 4.5:1. Settings offers deependhq.com's blue `#4A7BF7` and navy, and Champ Robin's original marigold-ink `#8A5A00`.

## 3. Typography Rules
| Role | Font | Size / weight |
|---|---|---|
| Display (greeting, titles) | Bricolage Grotesque | 30px/1.08 600 (hero), 17–18px 600 (bars) |
| Body | Figtree | 15px/1.5 400 |
| Labels | Figtree | 13–13.5px 600 |
| Eyebrow | Figtree | 11.5px 700, +0.06em, uppercase |

Fonts are loaded from Google Fonts into the host document (`loadFonts: false` turns this off). The fallback is the system UI stack.

## 4. Component Stylings
- **Logo mark** (Champ Robin logo pack, `robin-mark.svg` / `robin-mark-snow.svg`): a swallow in flight, wing swept back and forked tail, heading up and to the right. It is one vector path used as a CSS mask, so it is sharp at every size and takes any colour: navy `#0E1A33` on light, paper cream `#F4EBD9` on dark (`--logo`), the launcher's ink on the launcher, the brand colour when one is chosen in Settings. No disc behind it.
  - **Live**: three stacked copies of the mask are clipped to the tail, the body and head, and the wing, so the wing beats from its shoulder (pivot 60% 34%) and the tail flicks from its root (41% 64%) while the body moves; the body reaches a little under each so no seam shows. Wing beats are always in sync; at rest the bird glides (two quick flaps, then a hold, 3.4s) with a gentle rise and tilt.
  - **Ring** (guide v4): in the header and beside answers the swallow sits in a fine 90% ring (22% of the logo colour, about 1px on screen at any size) with the gap centred at the bottom, and a darker 10% arc (85%) revolving round it every 2.4s, staying in view as it crosses the gap. The swallow is at 72% of the ring's size.
  - **Where**: the launcher, the teaser, the title-pill presence, beside every answer, Home, a new conversation and the Settings preview all fly. In lists (Messages rows, "pick up where you left off") the swallow sits still on a soft grey disc.
- **Launcher**: 56px marigold disc carrying the navy live swallow (34px). The swallow morphs into a chevron-down when the panel is open. It is hidden in full-height mode.
- **Size stepper**: one chevron in the header: ⌃ at half height (to full), ⌄ at full height (back to half). There is no chevron to minimise from half; ✕ closes the chat. With one chevron left, the pill drops away so it matches the icons beside it.
- **Expand icon**: in a conversation's header only (half and full), left of the stepper; Home, Messages and Settings never show it, and leaving the conversation returns to normal width. Diagonal arrows out (⤢) widen the panel to half the screen at full height; arrows in (⤡) go back. Hidden below 900px.
- **Quick-start chips**: rounded pills with a leading line icon (help / calendar / tag), navy text and marigold icons; hover tints them pale marigold.
  - **Hover**: the tile tints pale marigold, its text turns deep marigold, and its icon sits in a small circle that fills marigold with the glyph turning white. The same happens on the conversation screen's quick starts.
- **Icon hover** (every screen): every icon button turns marigold-ink `#8A5A00` on hover, on a pale marigold wash with a pale marigold ring and a soft marigold glow. This covers the header buttons, the size chevrons, ✕, the input's + and voice buttons, and Copy, Read aloud, 👍 and 👎. The title pill's chevron turns marigold too.
- **Tooltips**: they replace the browser's grey ones everywhere in the widget. Each is a small navy label (white 11px semibold text, 3px by 8px padding, 7px radius) with a 4px arrow pointing at the control, 6px away from it. It shows above the control, or below when there's no room, and stays inside the window. It fades and slides in quickly (0.1s fade) after 0.15s on hover, at once on keyboard focus, and never on touch. A control's `title` becomes its tip, and it keeps its aria-label.
- **Teaser** (the card above the launcher): a white card with a flowing cream-to-marigold edge (20px radius, the corner nearest the launcher 6px). It holds the logo, "Robin · now", a ✕ (it turns on hover), typing dots that become the message, and two quick starts that open straight into that conversation. It springs up from the launcher; the quick starts rise in once the message shows.
- **Conversation footer**: one short line in 11px. It reads "By chatting with us, you agree to our Privacy Policy" (marigold link) when `privacyUrl` is set, otherwise "AI responses can make mistakes. Check important info."
- **Bubbles**: bot bubbles are surface-coloured with a hairline border and a 6px tail corner; user bubbles are paper cream.
- **In-chat cards** (lead form, slots, confirmation): surface card, 18px radius, small shadow.
  - **Details form**:
    - **Head**: a 32px marigold icon tile, the title (15.5px) and hint, and a "1 of 3" count that turns green when everything is filled. Under it, a 4px bar fills with a marigold gradient as required fields are completed.
    - **Fields**: 46px, 14px radius, 8px apart, with floating labels. The label sits inside the field and moves up small when you type or focus (marigold while focused).
    - **Checking**: a field that's right gets a green tick that springs in. A wrong or empty field shows its message, a red edge and a shake, but only after you leave it or press submit.
    - **Enter** moves to the next field and submits from the last one. The navy submit button gains a lift once everything is valid.
  - **Booking picker**:
    - **Days**: compact tiles ("MON / 26 / OCT", with the date in 18px display type) over a navy marker that slides to the chosen day.
    - **Times**: 34px pills, grouped under Morning, Afternoon and Evening. They slide in from the side you moved towards, group by group.
    - **Picking a time**: it turns navy with a tick that pops, without the grid redrawing.
    - **Footer**: names the picked time, with a calendar icon, beside a navy **Book it** button that pops in when enabled.
  - Cards use 12px/14px padding, so they stay compact in the chat.
  - **Confirmation** ("You're booked!", "Thanks…"):
    - **Look**: a card like the others with a faint green wash across the top, a 34px green badge with a tick beside the navy title, and the details as rows with 26px green icon tiles, split by dashed lines like a ticket.
    - **Motion**: the badge bounces in and draws its tick, then a green ring spreads and eight small dots (green, marigold and cream) burst outwards. The title rises in and the rows slide in one after another.
- **Input box** (pattern from deependhq.com): a single box with a 16px radius and a hairline border. It holds a 32px **+** button, the text field, a 32px waveform voice button and a 32px square send button, which is marigold when active and a sunk grey when disabled.
  - The **+** menu opens upward and the + rotates 45° into an ×. The emoji picker floats above the box: search field plus an 8-column grid.
  - While dictating, the box shows a red dot, a marigold level meter, a timer and ✓ / × buttons.
  - Attachment chips sit inside the box, above the text.
- **Call screen**: a navy-night radial background with Robin's stage in cream on a marigold glow (tap it to interrupt): rings closing in while listening (the ring thickens with the mic level), sound arcs while speaking, thought bubbles while thinking, a broken red ring on error. A status line and captions sit below. It has 56px round controls; End is red (`#E5484D`). The marigold glow is the one sanctioned glow in the widget.
- **Conversation screen** (subject-neutral, so it suits any assistant):
  - **Canvas**: clean white, with no glows, patterns or wallpaper, so the loader and the answers carry the screen.
  - **Header**: no menu, so every control is in view, each a round button with a thin border (36px), in dark navy `#1A1D3A`. On the left are the home button and the title pill (presence logo, `appName` and a chevron), which opens the conversations menu: new conversation, recent ones, all conversations. On the right are the wider-view button (expand / shrink; half the screen and back; hidden below 900px), the size chevrons as one bordered pill (up = bigger, down = smaller; only the ones that apply show), settings, and close.
  - **Chat history sidebar** (wide view only, on screens 1100px and up): a 248px column on the left under the header, on paper cream. At its top, "CHATS" with a hide button (sidebar icon) above a full-width **New conversation** button in the brand colour, then past chats grouped under Today / This week / Earlier; the open one sits on a white chip. Hiding it shows a sidebar button at the left of the header to bring it back; the choice is remembered. A conversation joins the list as soon as its first question is sent.
  - **Idle**: the gliding swallow in its ring (104px), "How can we help?", one line of help and the quick starts, centred.
  - **Messages**: the visitor's question sits in a light-grey bubble (`#F1F1F5`, radius 20/20/6/20) on the right; with a brand colour chosen in Settings it is solid in that colour.
  - **Answers**: Robin's answers are not bubbles.
    - Each one opens with a name line: the gliding swallow in its ring (34px; the text below is indented 38px), "Robin" in navy, and the time. The logo spins in as the answer arrives.
  - **Presence**: the 32px swallow in its ring in the title pill (the ring nearly fills the pill's height; the ring turns green when an answer arrives and red on an error, and the thinking arc runs along it) shows what Robin is doing. It has a small 14px badge at its lower right (it pops in on every change) and a fine 1.5px ring or soft waves hugging it, in the state's colour. Nothing reaches outside the title pill.
    - Ongoing activity decides the state. Listening (dictating, or a voice call listening) outranks speaking (read aloud, or a voice call speaking), which outranks thinking or writing, which outranks the emoji picker.
    - Short events flash over it for a moment, but never over a live mic or voice.
    - The swallow itself acts out each state too (build guide motions).

    | State | Badge | Ring and motion | Swallow |
    |---|---|---|---|
    | idle | none | none | glides |
    | listening | red mic | two soft red waves spread in turn; the badge throbs gently | pulses, wings beating slowly (1.2s) |
    | muted | grey mic-off | faint, still grey ring | glides |
    | speaking | marigold speaker | the same waves in marigold, a little faster | quick bob, wings at .6s |
    | thinking | marigold sparkle | a fine marigold arc chases round; the sparkle twinkles | hovers and tilts, gliding (2.6s) |
    | writing (streaming) | marigold pen | the same arc, slower; the pen moves | pecks, wings beating fast (.55s) |
    | emoji (picker open) | amber smile | the smile wiggles | pecks |
    | attaching (1.4s) | navy clip | the clip wiggles | glides |
    | done (1.2s, answer arrived) | green check | none | swoops in and lands |
    | stopped (1.2s) | navy stop | none | glides |
    | error (2.2s) | red alert | none | shakes, wings flutter, then droops |
    - The content runs full width beneath it, indented to line up with the name, in 15px text at 1.65 line height.
    - Text supports bold (navy), `code` on a soft grey chip, marigold underlined links, and bullet and numbered lists with marigold markers.
  - **Suggestion chips**: white pills with a thin border, navy text and marigold icons; hover tints them pale marigold, and the chosen one turns navy.
  - **Cards** (forms, time slots, info): an 18px radius with a hairline and a soft shadow, navy buttons and selected slots, marigold focus rings and header icons. Errors sit on a faint red card with **Retry**.
  - **Actions** under each answer: Copy (turns into a ✓), Read aloud (browser voice; press again to stop), 👍 and 👎 (toggle; sent as a `response_feedback` event). They always show, under every answer.
  - **Answer motion**, in order:
    1. The swallow beside the name spins in.
    2. The words fade in one by one from a soft blur. Only text is split, so links and bold still work. Long answers speed up so the reveal takes about a second.
    3. Chips pop in one after another.
    4. Cards catch one soft marigold light sweep.
    5. Copy, Read aloud, 👍 and 👎 pop in last.
  - **Robin's stage** (the signature element, `robinStage()`, from the Champ Robin build guide v4): the live swallow inside a 90% ring whose 10% gap stays centred at the bottom, on a soft aura (at idle the ring closes and a darker 10% comet circles it every 2.4s, like the small ring). Each state has its own sign, so it reads without any text.
    - **Layout**: the guide's 320×280 box (ring r 116, swallow 168px, a 36px badge sitting in the gap), scaled down: 144×126 in the thread, 198×174 over the chat (thinking, opening), 160×140 in a voice call (198×174 full height).
    - **Colour**: the ring, its comet and the signs use the swallow's colour (navy on light, paper cream on dark, cream in the call). Success turns the ring green `#12B76A`, error red `#D92D20`. The aura is a faint neutral glow (marigold in the call).
    - **Ring**: a base circle (1px, 22% opacity) and a brighter comet segment, redrawn every frame by one animation-frame loop (it stops a second after the stage leaves the page). Stroke widths are kept in screen pixels at any scale.

    | State | Sign | Ring | Badge |
    |---|---|---|---|
    | loading | the swallow fills up like liquid (a wavy line rising through a 14% ghost of it), hovering with a slow flap | gap 10, faint | none |
    | thinking | thought bubbles rise from the head, small to large; it hovers and tilts, gliding | a bright comet circles (1.4s a turn) | none |
    | search (while the backend reports searching / looking up / browsing) | a handle grows from the ring's lower right, so it reads as a magnifying glass; the swallow hovers and glides inside the lens on a slowly turning aura | closed, darker (75%, 1.6px) | none |
    | listen (call) | rings close in on the swallow; it pulses, wings beating slowly | gap 14; thickens and brightens with the mic level | mic |
    | talk (call) | ")))" sound arcs leave the beak; it bobs quickly | gap 12; a comet runs in speech bursts | speaker |
    | muted (call) | it rests | gap 14 | mic off |
    | error (call) | it shakes, wings fluttering, then droops | breaks into red fragments that jitter | red ! |
    | chat, idle, success | (beak dots; calm glide with a breathing ground shadow; swoops in to land as the ring closes green) | | |

    - **Swap**: on a new state the swallow dips out (fade, scale .88, 200ms), then the state sets in and its clock restarts. Badges pop in.
    - **Reduced motion**: no loop, no aura or trails; the loading fill shows full, and the ring shows the state by colour and badge only.
  - **Opening the chat** (launcher or teaser click; `openingTransition`), inside the chat window only, never over the page:
    1. The chat opens at once, covered by its own white layer with the stage in the middle, filling up once (a 1s fill). The chat's content waits underneath, not displayed.
    2. When the chat is ready (web fonts loaded, capped at 1.5s) and the loader has shown for at least 0.75s so it never flickers, the layer fades and the stage swells away. The content appears, so its own entrance animations (rising header, chips and input) play then.
    3. The layer is removed after 0.46s.
    - Closing the chat (launcher, Escape or close) during the opening ends it. Reduced motion opens directly.
  - **Thinking, in the chat window** (`thinkingOverlay`):
    - Sending a question covers the chat window only, never the page, with the same blurred layer, clipped to the panel's rounded corners. The stage sits in its middle: loading (filling) for the first 1.2s, then thinking.
    - Under it are the status line (17px, semibold, with a light sweeping through it) and a navy **Stop** pill, which takes focus. Escape stops too.
    - The layer lifts (fade, blur clears, the stage swells away) the moment the answer arrives or starts streaming, so the answer is seen arriving. Errors and Stop lift it as well.
    - Closing the chat lifts it; reopening while still thinking brings it back.
    - With the option off, during a voice call or with reduced motion, the stage shows in the thread instead (below).
  - **Thinking in the thread**: the stage (loading, then thinking) sits in the middle of the space under the question, with a marigold-ink `#8A5A00` status line beneath it. That line says "Thinking", then only what the backend reports (`onStatus`), fading between messages. When the answer arrives (or starts streaming), the loader lifts out of the flow and fades, so the answer takes its place without a jump.
  - **Composer**: a floating panel (30px radius, thin border, soft shadow) above the bottom edge, with the text on top and the controls underneath. On the left are a round **+** (attach, emoji, dictate) and the voice button; on the right, a round navy send button with a right arrow. While a reply loads, send becomes a dark stop button with a white square. Focus draws a cream-to-marigold edge; while generating, that edge flows back and forth. Under the panel sits the disclaimer ("AI-generated responses may contain mistakes. Please verify important information.").
  - **States**: idle → submitted (the question appears, the loader starts at "Thinking") → processing (reported steps) → streaming (text grows with a pulsing marigold dot at the end) → done. Stop keeps any streamed text and notes "Response stopped". An error stops the loader and shows a message with **Retry**.
- **Tabs**: Home / Messages. The active tab gets a pale marigold pill (it slides between tabs) and a marigold icon, with navy text.
- **Home** (conversation style):
  - **Header**: the conversation header's look, with the presence logo and "Robin" on the left, and the size chevrons, settings and close on the right.
  - **Greeting** (centred): the gliding swallow in its ring, then "Hi there." in grey and "How can we help?" in navy (22px display, 20px in half view). On Home the ringed swallow above it is 128px, with tight spacing round the greeting.
  - **Live mark** (Home, a new conversation and the Settings preview): the swallow glides inside its ring on a faint breathing glow in the accent colour (11%, pale marigold or the chosen brand colour), with a soft ground shadow under it that narrows and fades as it rises (3.4s, in step with the glide). No trails. Reduced motion drops the glow and holds the swallow still; the shadow stays.
  - **Ask field**: it looks like the conversation input (placeholder, navy arrow circle), takes the cream-to-marigold edge on hover, and opens a conversation.
  - **Cards**: these are white 18px cards with small caps titles.
    - "Pick up where you left off": the last conversation, named by its first question, with the last message under it and how long ago.
    - "Popular questions": rows with marigold icon tiles that fill marigold on hover.
  - **Motion**: everything rises in turn.
- **Messages** (conversation style):
  - **Header**: "Messages" (20px display) with a pale marigold count badge, then the size chevrons, settings and close.
  - **Search**: a field under the header in the Home ask field's style (white 24px pill, hairline that turns cream-to-marigold on hover and focus, search icon that turns marigold on focus), "Search your chats". Typing narrows the rows to chats containing every word, in the title or any message; a × clears it (Escape too). With no match: "No chats match your search." Shown once there is at least one chat.
  - **Rows**: each conversation is its own card row (logo, title and time, a one-line preview, an arrow). Rows tint pale marigold on hover and arrive one by one.
  - **Empty state**: the gliding swallow with a short note.
  - **New conversation**: a navy pill.
- **Settings** (conversation style):
  - **Header**: back and "Settings" on the left, then the size chevrons and close.
  - **Header**: Back returns to the screen Settings was opened from (Home, Messages or the conversation). The settings button is on all three and is always shown.
  - **Live preview card** (first, just above Appearance): a small copy of the chat that follows every choice at once: the ringed swallow, a "Hi there." user bubble, Robin's "Sure, I can help with that." with its mark, an input box with its send button, and the launcher beside "Live preview". It shows the scheme, brand colour, text size and motion as they will look.
  - **Appearance card**: Light / Dark / Device, with a white pill that slides to the choice. The chosen icon is marigold. Under it, **Brand colour**: round 28px swatches (the chosen one gets a ring and a tick): Default (half black, half marigold), the site's colour, marigold-ink `#8A5A00`, and deependhq.com's palette: marigold `#F4A62A`, blue `#4A7BF7` and navy `#0E1A33` (a swatch equal to the site's colour is shown once).
    - **Default** is the designed look: the navy Robin mark, marigold accents, paper-cream user bubbles, the site colour on the launcher and buttons.
    - **Any other swatch** colours the whole widget on every page: the swallow and its ring, the accent family (icons, chips, links, tints, focus edges, loaders' status line), the user's bubbles, and every filled control (launcher, send, Home's ask arrow, New conversation, form buttons, chosen chips and slots, Stop). Dark scheme uses lighter shades of it. The choice is remembered.
  - **Text size card**: three "Aa" options (small 13.5px, default 15px, large 17px) on a sliding pill. It scales every screen as a whole (header, messages, forms, chips, cards, Home, Messages, Settings, input and tabs) by 0.9 / 1 / 1.133, so 15px text becomes 13.5px or 17px and everything keeps its proportions. The panel itself keeps its size.
  - **Reduce motion card**: a switch, "The swallow stays still and loaders stop spinning". On, everything holds still as with the device's reduced-motion setting; off, the widget animates even if the device asks it not to. Remembered.
  - **Privacy card**: "Clear conversation history" as a row with a red icon tile, red title, a one-line note and an arrow.
- **Confirmation dialogs** (no browser `alert` / `confirm` / `prompt` anywhere): a card centred over a soft scrim on the panel (18px radius, large shadow), an icon tile, a 16.5px display title, a line of detail and two pill buttons: the safe one ("Keep chats", "Keep booking", "Cancel") on a sunk fill and focused first, the action on the danger colour (navy text in dark mode), or on the site colour for a non-destructive one (Rename's "Save", with a 16px text field). Esc or a tap outside is the safe answer, Tab stays inside, and focus returns to where it was. Used for clearing history, cancelling a booking and renaming a conversation.
  - Changing a setting redraws in place: the scroll position stays and the cards don't replay their entrance.
  - **Wide**: opened from a wide conversation, Settings stays wide, with the preview kept in view on the left and the cards on the right.

## 5. Layout Principles
4px base grid. Panel insets are 14–16px. Grouping is tight (6–8px) inside elements and looser (12–14px) between them. Content is left-aligned.

| State | Desktop size | Mobile (≤480px) |
|---|---|---|
| hidden | launcher only | launcher only |
| half | 400 × max(480px, 52vh) | sheet, 62dvh |
| full | 440 × (100vh − 32px), launcher hidden | 100dvh |
| wide | max(440px, 50vw) × (100vh − 32px); thread and input centred, max 780px | n/a (hidden) |

## 6. Depth & Elevation
Panel: `0 24px 60px -12px rgba(30,25,21,.32)` plus a 1px ink ring at 6%. Cards: `0 1px 2px` plus a soft `0 6px 18px -6px`. No glows and no glass.

## 7. Do's and Don'ts
- Do use one marigold disc as the only decoration, and use display type for emphasis.
- Don't use emoji as UI, gradient text, coloured side-stripe borders, glassmorphism, or cyan accents.
- Don't ask for an email on open. Only ask when it's needed (booking, quote).

## 8. Responsive Behavior
- **Device class:** pointer surface (desktop and phone web). There is no foldable-specific layout; on phones the widget becomes a bottom sheet with a grab handle that cycles size.
- Respects `env(safe-area-inset-bottom)`. Touch targets are at least 40px, and the stepper becomes 40px on mobile.
- **Motion budget:** only height, width, opacity and transform change (plus stroke-dashoffset for drawn checkmarks). Everything uses one easing, `cubic-bezier(.16,1,.3,1)`: 420ms for panel resizes, 300–500ms for entrances, 120–250ms for press and hover feedback. There's no bounce or elastic motion, and staggers are 40–60ms per item. `prefers-reduced-motion` turns all animation and transitions off, including pseudo-elements, and drawn checkmarks show fully drawn.

### Icons

One line-icon family: 24px grid, 2px stroke, round caps and joins, `currentColor`. There are no emoji in the UI chrome. Icons sit beside their text and are never tiles stacked above headings. Each icon is wrapped in `.i.i-NAME`, so each can have its own hover motion:

| Icon | Hover motion |
|---|---|
| help, messages, user, mail, monitor | small bob up |
| calendar | page flip (vertical squash) |
| tag | swing from its hole |
| headset, phone, trash | wiggle |
| check | pop |
| sun, clock | half turn |
| moon | tilt |
| trending, external | nudge up and right |
| arrow-right (in buttons and links) | slides 3px right |

Ambient loops (slow, subtle, and off under reduced motion):
- **Live icons**: icons sit still until the pointer is on them (or on the row, chip or card holding them); then each plays its own move on a 1.8s loop for as long as the pointer stays. Disabled buttons stay still. This covers content icons (quick-start chips, Home rows, eyebrows, reply chips, form headers, Settings) and chrome icons: the launcher chat icon wiggles, tab icons bob, the gear turns slowly, × and + make a quarter turn, the chevrons point the way they go, Back steps left, the voice waveform pulses, row arrows slide right, and the call controls pop.
- `motion: 'full'` keeps all of this on even when the device asks for reduced motion. The demo page uses it.
- The empty-state art floats and its sparkle twinkles.
- The call-screen waveform pulses, and the phone in the call bar wiggles.
- The footer sparkle twinkles three times on load, then stops.

### Motion inventory

| Where | Motion |
|---|---|
| Launcher | Pops in on page load. When the teaser appears it sends out a ring pulse and the icon wiggles. The chat icon morphs into a chevron when open. The unread badge pops in. |
| Teaser | Robin shows typing dots for about 0.9s, then the message fades in. |
| Home | The swallow glides; the greeting, ask field and cards rise in turn; row icons fill marigold on hover. |
| Messages | Conversation rows arrive one by one and tint pale marigold on hover; the empty state rises in. |
| Settings | The cards rise in turn when Settings opens (not again when a setting changes); the appearance and text size pills slide to the choice; the chosen swatch gets its ring and tick; the switch knob slides. |
| Tabs | One pill indicator slides between Home and Messages. |
| Chat | User bubbles slide in from the right, Robin's from the left. Blocks inside a reply (text, form, slots) stagger. Messages already there when a thread opens don't animate. New messages scroll smoothly into view. |
| Buttons | Everything squishes to 0.9 when pressed. Hover nudges: × turns 90°, the gear spins, Back steps left, chevrons point the way they go, and the waveform stretches. |
| Input box | Send pops when it becomes available, and its arrow flies up on send. **+** turns into ×, and menu items stagger in. Emoji grow on hover. Attachment chips pop in and shrink out. |
| Forms | Fields and day tiles arrive one by one. Labels float up. A field that's right springs a tick; invalid fields shake. The progress bar fills. Day changes slide the marker and the times; a chosen time pops. Checkmarks draw themselves. |
| Voice | Controls rise in. The stage acts out the call: rings close in while listening (the ring tracks mic level), arcs leave the beak while speaking, bubbles rise while thinking. The "In a call" bar slides down. |

## 9. Agent Prompt Guide
"Navy `#0E1A33` type with a deependhq.com marigold `#F4A62A` launcher (navy-dark ink on it), pure white body `#FFFFFF`, Bricolage Grotesque display with Figtree body, tan hairline `#EAE3D5`, marigold used only for the launcher and primary actions; the navy swallow and marigold accents everywhere else."
