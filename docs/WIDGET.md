# The in-app widget: `<deep-assistant>`

The assistant as a **web component**: one dependency-free JavaScript file served by the assistant itself, usable in
any application (React/Next.js, Vue, Angular, plain pages). It keeps every server feature (cited answers, booking,
hand-over, feedback, tracking, console) and adds what an in-app widget needs: it inherits your app's font, is styled
through CSS variables, knows who is signed in, and emits events your app can react to.

This is what deependhq.com uses: `static/widget.js` is a 2 KB loader that draws the "ask" button and mounts the
component on the first tap (`docs/WIDGET_SWAP.md`). Any other page or application can embed the component directly
as below. Live demo: `/demo` on the assistant (`WIDGET_DEMO=true`); site-style test page: `/static/embed-test.html`.

## 1. Embed

```html
<script type="module" src="https://assistant.example.com/static/deep-assistant.js"></script>
<deep-assistant api="https://assistant.example.com" mode="launcher" theme="auto"></deep-assistant>
```

| Attribute | Values | Notes |
|---|---|---|
| `api` | URL | the assistant server; its origin must be in `ALLOWED_ORIGINS` of the app's origin… see §4 |
| `mode` | `panel` (default) / `launcher` | panel fills its container (give it a height); launcher is a floating button + pop-over |
| `theme` | `light` (default) / `dark` / `auto` | auto follows the OS; the ⋯ menu's theme item is remembered in localStorage |
| `open` | boolean attribute | launcher open state |
| `token` | string | signed-in visitor token (§3) |
| `user-name`, `user-email` | strings | unverified prefill hints when no token exists |
| `title`, `subtitle` | strings | header copy (default `Deep` / `AI assistant`) |
| `greeting` | string | intro line on the welcome screen (default: what the assistant can do) |
| `suggestions` | `a\|b\|c` | up to four welcome actions; booking phrasings ("Book…", "Schedule…") open the booking card, others are sent as questions. Default: picked from the page (see `page-context`) |
| `page-context` | `general` / `product` / `solutions` / `contact` | which welcome actions to show; default inferred from the host page URL (`/product…`, `/solutions…`, `/contact…`, `/pricing…`) |
| `tabs` | `home,messages,help` | sections; leaving out `help` removes Help from the ⋯ menu; History is always kept |
| `shortcut` | `Label\|https://…` | external scheduler link in Help (default: the Zoom booking page); `""` hides it |

Methods: `ask(text)`, `book(callType?)` (opens the in-chat booking card; `callType` such as `'walkthrough'` marks the
matching meeting as suggested), `open()`, `close()`, `toggle()`, `newChat()` (alias `reset()`), `openConversation(id)`,
`showView('chat'|'history'|'help')` (`'messages'` still works), `setToken(token)`. Properties: `busy`, `sessionId`, `view`.

### History

The header has a History button (clock icon, with a red badge counting conversations that have unread assistant
messages) and a ⋯ menu (New conversation, Help & contact, Download transcript, Dark/Light theme). There is no bottom
tab bar: the conversation stays central and History and Help open as sub-screens with a back arrow. Esc closes a
menu, then leaves a sub-screen, then minimizes the launcher.

History lists the visitor's past conversations, newest first, grouped under Today / Yesterday / Previous 7 days /
Older, with a search box and a "New conversation" button. Each row shows the title, a one-line preview, the relative
time (`14m`, `11h`, `2d`) or a "Current" tag, and a dot when unread. Loading shows skeleton rows; a failed request
shows an error state with "Try again"; an empty list explains what will appear there. Tapping a row loads the full
history (sources, ratings, copy) and marks it read. Conversations belong to the browser's visitor id (localStorage)
or, when a token is set, to the signed-in user, so a signed-in visitor sees their conversations across devices.

Each row shows an AI-generated 3–6 word title (made in the background after the first exchange by
`app/titles.py`; fallback: the first message cut to ~40 characters; "Quick hello" for greeting-only chats until a
real question arrives; regenerated once at the 6th visitor turn; a rename from the row's ⋯ menu or a long-press is
final), a one-line preview, the relative time and an unread dot, grouped under Today / Yesterday / Previous 7 days /
Older, with a search box.

Server side: `GET /conversations`, `GET /conversations/{id}`, `POST /conversations/{id}/read`,
`PATCH /conversations/{id}` `{title}`, `POST /conversations/{id}/title?force=1` (all need `X-Visitor-Id` or a
visitor token), `sessions.last_read_at/title/title_source/title_turns`, `app/conversations.py`, `app/titles.py`.

Events (all `CustomEvent`, bubble through the DOM, `detail` below):

| Event | detail |
|---|---|
| `deep-assistant:ready` | `{sessionId}` |
| `deep-assistant:question` | `{text}` |
| `deep-assistant:answer` | `{question, answer, sources:[{n,url,title}], messageId, failed}` |
| `deep-assistant:sources` | `{items}` |
| `deep-assistant:booking` | `{status: 'started'\|'confirmed'\|'pending_zoom'\|'unavailable'\|'slot_taken', bookingId, joinUrl, handoffUrl, slot, schedule, email}` |
| `deep-assistant:handover` | `{leadId, email, briefSent}` |
| `deep-assistant:feedback` | `{messageId, rating: 1\|-1, note}` |
| `deep-assistant:action` | `{action, label, kind}`: `suggestion` (welcome action), `followup`, `help`, `help_question`, `booking_type`, `booking_time`, `handover_requested`, `handover_form`, `unanswered` (low-confidence answer) |
| `deep-assistant:open` / `:close` / `:error` / `:view` / `:voice` / `:upload` | |

The component installs no analytics of its own. To measure conversion, forward these events to whatever the host
page already uses, e.g. `el.addEventListener('deep-assistant:action', (e) => analytics.track('deep_' + e.detail.action, { label: e.detail.label }))`.
Only `question` and `unanswered` carry visitor-typed text; booking events carry the email the visitor entered, so
leave that field out if your analytics must not hold personal data.

Theming (Indigo Dream): set CSS variables on the element: `--da-primary --da-primary-hover --da-navy --da-lavender
--da-bg --da-surface --da-success --da-text --da-muted --da-line --da-radius --da-font`. The font defaults to Inter
(when the page has it) then system UI fonts, never the host page's font; set `--da-font: inherit` to use your app's font.

## 2. Wrappers

**React / Next.js (ChampSet)**: copy `widget/react/DeepAssistant.tsx` to `frontend/components/DeepAssistant.tsx`
and render it once in `app/layout.tsx`, next to `<HelpButton />`:

```tsx
import { DeepAssistant } from "@/components/DeepAssistant";
…
<DeepAssistant api={process.env.NEXT_PUBLIC_ASSISTANT_URL!} mode="launcher"
  onBooking={(d) => console.log("booked", d)} />
```

Add `NEXT_PUBLIC_ASSISTANT_URL=http://localhost:8080` to ChampSet's `.env`. The wrapper detects `@clerk/nextjs`
and passes the user's session JWT automatically, refreshed every 50 s.

**Vue 3 (ChampOracle)**: copy `widget/vue/DeepAssistant.vue` to `frontend/src/components/DeepAssistant.vue`,
tell Vite the tag is a custom element, and render it in `App.vue`:

```js
// vite.config.js
vue({ template: { compilerOptions: { isCustomElement: (tag) => tag === 'deep-assistant' } } })
```
```vue
<DeepAssistant :api="assistantUrl" mode="launcher" :token="assistantToken" @booking="onBooking" />
```

## 3. Signed-in visitors

Pass a token in the `token` attribute. The assistant then greets the user by first name, books without asking
for name and email (verified identity only), prefills the hand-over form, and stores the user on the session so the
console shows who was talking. The server accepts two formats in the `X-Visitor-Token` header:

**a. HMAC token minted by your backend** with the shared `WIDGET_SIGNING_SECRET` (any language, three lines):

```js
// Node (Fastify/Express): GET /assistant-token, behind your own auth
import { createHmac } from "node:crypto";
const payload = Buffer.from(JSON.stringify({ sub: user.id, name: user.name, email: user.email, exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url");
const sig = createHmac("sha256", process.env.WIDGET_SIGNING_SECRET).update(payload).digest("hex");
reply.send({ token: `v1.${payload}.${sig}` });
```
```python
# Python (Flask): from the assistant repo, app/identity.py
from app.identity import mint
token = mint(user.id, user.name, user.email, ttl_seconds=3600, secret=os.environ["WIDGET_SIGNING_SECRET"])
```
Never mint in the browser; the secret must stay on your server. Tokens expire; mint a new one per page load.

**b. Clerk session JWT** (ChampSet): set `CLERK_JWT_ISSUER_DOMAIN` on the assistant to the same value ChampSet
uses. The assistant verifies the RS256 signature against `{issuer}/.well-known/jwks.json`, the issuer and expiry.
Clerk's default session token carries only the user id; to let the assistant book without asking, add `email` and
`name` (or `first_name`/`last_name`) claims in Clerk → JWT Templates, or pass `user-name`/`user-email` hints
(then the assistant confirms the email once before booking, because hints are unverified).

## 4. Server settings

| Variable | Purpose |
|---|---|
| `ALLOWED_ORIGINS` | add every origin that embeds the component (dev: `http://localhost:3500` ChampSet, `http://localhost:3000` ChampOracle) |
| `WIDGET_SIGNING_SECRET` | shared secret for HMAC tokens |
| `CLERK_JWT_ISSUER_DOMAIN` | enables Clerk JWT verification |
| `WIDGET_DEMO` | serves `/demo` and `/demo/token` (a sample user); `false` in production |

`GET /me` with the token header returns what the widget may show: `{signed_in, name, email, verified, via}`.

## 5. The interface (Indigo Dream, light by default)

Tokens: primary `#5546F7` (hover `#4537E8`), midnight navy `#151B32` (header, voice view), lavender `#EEECFF`
(visitor bubbles, selected states), app background `#F6F7FC`, surfaces `#FFFFFF`, success `#19B887`, text `#151B32`
/ `#68718A`, borders `#E4E7F2`. All colours are CSS variables in `:host` of `static/deep-assistant.js`; `theme="dark"`
swaps the neutrals for a navy palette (and a lighter indigo for text so it stays readable).

Launcher: 56 px indigo button with the Deep mark, a green dot only while `/healthz` answers, an unread badge, and a
chevron while open. The panel animates in from the button (opacity + 14 px rise; no motion under
`prefers-reduced-motion`). Header (navy): avatar, **Deep**, "AI assistant · ● Online" (Connecting… until the health
check returns, Offline when it fails and is retried every 20 s, Working… while answering, In a call during voice),
History, ⋯, Minimize and Close (launcher mode only; Close also ends a voice call and stops a reply).

Welcome screen (empty conversation): "Hi! I'm Deep 👋" (with the first name when the visitor is known), the intro
line (`greeting`), and four actions chosen for the host page: on general pages *Explore data solutions*, *Find the
right solution for my business*, *Learn about LakeB2B*, *Book a meeting*; product pages lead with the product and a
walkthrough; contact/pricing pages lead with booking and *Talk to a person*. Questions go through `/chat` like typed
ones; *Book a meeting* opens the booking card directly from `GET /booking/availability` (no model call). The input
is always available.

Conversation: white bot bubbles with a 6 px tail corner and a "Deep · 2m" line, lavender visitor bubbles. While the
agent works, a status pill shows the real backend step (Searching…, Writing…) above a skeleton bubble, then collapses
into "Worked for 3s · 2 sources". Answers render bold, bullet and numbered lists, headings, inline code, links and
`[n]` citation pills; a "Sources" row and thumbs / copy tools follow (always visible on the latest answer and on
touch screens). New content only auto-scrolls when the reader is at the bottom; otherwise a "Latest" button appears.
Failed requests show a red-tinted bubble with a plain-language reason (rate limit, server error, offline) and a
"Try again" follow-up. Stop is the send button while a reply streams (Esc works too).

Follow-ups are never generic: after a low-confidence answer (`handover_offer`) the visitor gets *Ask the team
directly* and *Book a meeting*; after a failure, *Try again*; after a sourced answer about pricing or demos, at most one
*See it in a walkthrough* (or *Talk to an expert* for data/solution questions from the second question on), once per
conversation.

Booking card (one card, four steps with a progress bar and a back arrow; every choice survives going back):
1. *Choose a meeting*: the live call types with description, duration and "Zoom video call".
2. *Pick a time*: date chips with open counts and only the open times for that day, in the visitor's timezone.
3. *Your details*: name and email (skipped for a verified signed-in visitor), optional company and topic, with
   inline validation.
4. *Review and confirm*: summary, "Confirm booking", "Nothing is booked until you confirm."
Success only after `/booking/confirm` answers `confirmed` (or `pending_zoom`: "One last step on Zoom"): Join Zoom,
Add to calendar, and next steps. A taken slot returns to step 2 with a banner and the nearest open times; an
unavailable scheduler offers the external Zoom link; nothing is ever shown as booked before the server says so.

Help (⋯ → Help & contact): Book a meeting, Talk to a person (the hand-over form; replies by email), Voice
conversation (when the browser can listen), the external scheduler link (`shortcut`), what Deep can do, common
questions (the server's most-asked questions) and the privacy link.

Layout: floating panel `min(400px, 100vw − 40px)` × `min(700px, 100dvh − 112px)`, 20 px radius, above the launcher on
desktop; full screen under 520 px, sized to the visual viewport so the composer stays above the on-screen keyboard,
with safe-area padding and 16 px inputs (no iOS zoom). Footer: "By chatting, you agree to our Privacy Policy".
Thumbs-down opens a small popover (reason chips, optional note, Submit) and a "Thanks for the feedback" toast.

Accessibility: the panel is a labelled dialog (launcher) or region (panel), the log is `role="log"` and
`aria-busy` while streaming, status changes and booking results are announced through a polite live region, all
controls have labels and visible focus rings, the ⋯ menu supports arrow keys and Esc, focus moves to the step title
when the booking card changes step and back to the launcher when the panel closes.

## 6. Composer

One slim pill-shaped row (about 45 px) with an indigo focus ring: **+**, the input, the voice button and the round
send button. The input grows to five lines as you type; Enter sends, Shift+Enter adds a line. **+** opens a small
menu (arrow keys and Esc work) with Attach a file, Emoji, GIF (only when the server has a GIF key) and Dictate (only
when the browser or the server can transcribe). The voice button (wave icon) starts a voice conversation and hides
while you type; send is disabled until there is text or a finished upload and becomes Stop while a reply streams. If you see purple teardrops around the
text caret, that is Windows' Text cursor indicator (Settings → Accessibility → Text cursor), not the widget.

| Feature | How it works | Server / env |
|---|---|---|
| Attachments | picker or drag-and-drop onto the panel; preview chips with size, progress bar and ×; images, PDF, DOC(X), XLS(X), TXT, CSV, MD; the message carries the upload ids and the model sees extracted text (TXT/CSV/MD directly, PDF via pypdf); the chat shows `📎 name` in the visitor bubble | `POST /upload` (multipart, needs `X-Session-Id`), `GET /uploads/{id}`, table `uploads`, `UPLOAD_DIR`, `UPLOAD_MAX_MB` |
| Emoji | dark picker with search; inserts at the cursor | none |
| GIF | dark picker with search, proxied so the key stays on the server; sends `[GIF](url)` which renders inline | `GET /gifs?q=`, `GIF_PROVIDER=tenor\|giphy`, `GIF_API_KEY` (empty hides the button) |
| Dictation | Web Speech API fills the input (interim text shown, recording dot and timer, stop button); when `STT_PROVIDER=openai` the browser records and `POST /stt` transcribes (Groq Whisper by default); denied permission shows a message | `STT_PROVIDER`, `STT_API_KEY`, `STT_BASE_URL`, `STT_MODEL` |
| Speak to Deep | full-panel call view: logo, animated waveform, "Listening… / Thinking… / Speaking…", Mute and End call. Listens, sends the text through the normal `/chat` pipeline (so the transcript is saved like any message), speaks the answer (browser SpeechSynthesis, or `POST /tts` when `TTS_PROVIDER=openai`), then listens again | `TTS_PROVIDER`, `TTS_API_KEY`, `TTS_BASE_URL`, `TTS_MODEL`, `TTS_VOICE` |

`GET /widget-config` tells the widget what is enabled: `{privacy_url, upload_max_mb, upload_types, gif, stt, tts}`.

## 7. Testing

```
node scripts/browser_check_widget.mjs http://127.0.0.1:8080 out_dir
```
Drives the `/demo` page in headless Edge: anonymous panel answers with sources, events reach the host page,
the signed-in launcher identifies the user, books without asking for name or email, prefills the hand-over form,
and the session row in the console carries the user. Unit tests: `tests/test_identity.py`.
