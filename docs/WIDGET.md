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
| `theme` | `auto` (default) / `dark` / `light` | auto follows the OS |
| `open` | boolean attribute | launcher open state |
| `token` | string | signed-in visitor token (§3) |
| `user-name`, `user-email` | strings | unverified prefill hints when no token exists |
| `title`, `subtitle`, `suggestions` | strings | copy; suggestions are `\|`-separated |

| `tabs` | `home,messages,help` | bottom navigation; `messages` is always kept |
| `shortcut` | `Label\|https://…` | card at the top of the Messages screen (default: the Zoom booking page); `""` hides it |
| `greeting` | string | the bot's first message in a fresh conversation |

Methods: `ask(text)`, `open()`, `close()`, `toggle()`, `newChat()` (alias `reset()`), `openConversation(id)`,
`showView('chat'|'messages'|'help')`, `setToken(token)`. Properties: `busy`, `sessionId`, `view`.

### Messages screen

The bottom tab bar has Home (the current conversation), Messages and Help. Messages lists the visitor's past
conversations, newest first: bot avatar, bot name, one-line preview of the last message, relative time (`14m`,
`11h`, `2d`), and a red dot when a conversation has assistant messages the visitor has not seen. A red badge on the
Messages tab counts such conversations. Tapping a row loads the full history (sources, ratings, copy) and marks it
read; a back arrow returns to the list; "Ask a question" starts a new conversation with the greeting and quick
replies. Conversations belong to the browser's visitor id (localStorage) or, when a token is set, to the signed-in
user, so a signed-in visitor sees their conversations across devices.

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
| `deep-assistant:booking` | `{status: 'handoff'\|'booked'\|'unavailable'\|'slot_taken', leadId, handoffUrl, slot, schedule}` |
| `deep-assistant:handover` | `{leadId, email, briefSent}` |
| `deep-assistant:feedback` | `{messageId, rating: 1\|-1, note}` |
| `deep-assistant:open` / `:close` / `:error` | |

Theming: set CSS variables on the element: `--da-bg --da-panel --da-panel-2 --da-line --da-line-strong --da-text
--da-muted --da-scan --da-beam --da-beam-text --da-danger --da-font --da-radius`. The default is the electron-scan
look; the font is inherited from your app unless `--da-font` is set.

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

## 5. The interface (dark by default)

Header: logo, **ask deep >_**, muted "Deep can also help directly", a ⋯ menu (Switch theme, Download transcript,
New chat) and × in launcher mode; a back arrow when a conversation was opened from Messages. No meta bar: the
session and timezone still work in the background. Bot bubbles `#2A2B2F`, 20 px corners, with a muted
"Deep • AI Agent • 14m" line; visitor bubbles in the orange accent, right-aligned. Typing indicator while a reply
streams; auto-scroll. Under each answer: a compact "Sources" row of pill chips (number, title cut at 28 chars, domain,
tooltip with the full title, opens in a new tab) and small muted thumbs-up / thumbs-down / copy buttons that
appear on hover ("Copied" confirmation). Keyboard hint (Enter / Shift+Enter / Esc) only while the input is focused.
Footer: "By chatting with us, you agree to our Privacy Policy" (`PRIVACY_URL` or the `privacy-url` attribute).
First message: "👋 Hey <first name>, you're speaking with Deep's AI assistant…" when the visitor is known, else the
generic version; the site loader can override it with its `PROACTIVE.message`.

Theme: `theme="dark"` (default), `"light"`, or `"auto"`. The ⋯ menu's Switch theme is remembered in localStorage.

Layout: 400×700 floating panel (max-height viewport − 40px, 16px radius) on desktop, full screen under 480px;
header 64px; the messages area flexes and scrolls with a thin 6px scrollbar; the tab bar (56px) shows on Home and
Messages only and hides once a conversation has messages, where the header gains a back arrow to Messages.
Thumbs-down opens a small popover (reason chips, optional note, Submit) and a "Thanks for the feedback" toast.

## 6. Composer

Compact rounded box (`--da-cbox`, subtle `rgba` border, soft orange focus glow), input grows from one to five
lines, bottom row: 📎 attach, 😀 emoji, GIF, 🎤 dictate; on the right the "Speak to Deep" pill in the warm
gradient (`--voice-gradient-start/mid/end`, default orange → coral → rose) that becomes a round gradient send button
once there is text or an attachment. If you see purple teardrops around the text caret, that is Windows' Text cursor
indicator (Settings → Accessibility → Text cursor), not the widget.

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
