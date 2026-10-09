# Replacing the Widgo chat on deependhq.com with this assistant

Source repo of the site: https://github.com/Champ-Deep/deependhq-site (no-build React on Cloudflare Pages, pages
are generated nightly, so edit the templates / build script, not the published HTML).

## What is there today

| File | What it does | Action |
|---|---|---|
| `widgo-gate.js` (loaded on every page via `<script src="widgo-gate.js"></script>`) | Loads `https://cdn.widgo.ai/widgo.js` with org id `org_35e92c34c3fb4f43`; on phones shows its own 56px launcher first | **Remove** the script tag everywhere and delete the file |
| `ask.js` | A one-time inline feedback strip on post pages ("Did this page tell you what I actually do?"). Not Widgo. | **Keep** |
| Footer text: "the Ask Deep chat is run by Widgo and uses cookies" + link to widgo.ai cookie policy | Disclosure for the old widget | **Replace** (see below) |
| `visitor-id.js`, `segment.js`, `analytics.js`, `copy-engine.js` | Site's own first-party scripts | Keep |

## The change

1. Remove `<script src="widgo-gate.js"></script>` from every page template and delete `widgo-gate.js`.
2. Add, in the same place:
   ```html
   <script src="https://assistant.deependhq.com/static/widget.js" defer></script>
   ```
   (`assistant.deependhq.com` is the subdomain we deploy to; any name works as long as it matches
   `ALLOWED_ORIGINS` on the assistant and the DNS record exists.)
3. Footer line: change to something like
   "the Ask Deep chat answers from this site only, sets no cookies, records your IP address, approximate location
   and the page you came from, and emails Deep when you ask to book a call".
   The widget keeps a session id in the site's `sessionStorage` and a random visitor id in the site's
   `localStorage`, never a cookie. "No cookies" stays true; "no trackers" no longer does, because session origin
   tracking is on (`docs/TRACKING.md`). Drop that phrase from the footer.
4. `/privacy`: add that chat messages, booking details (name, email, reason, chosen time), the IP address with its
   approximate location, and the referring page are stored by the assistant for `TRACK_RETENTION_DAYS` (90) and
   that booking details are emailed to Deep; name the geo provider (ipwho.is by default) as a processor. The page is
   in the knowledge base, so the bot will cite it when asked.
5. Cloudflare → AI Crawl Control: allow the user agent `deependhq-assistant/0.1` so the nightly re-crawl is not
   challenged. (robots.txt already allows it.)
6. In the Widgo dashboard: deactivate the org or let the subscription lapse once the swap is live.

## Behaviour parity with widgo-gate.js

The new `static/widget.js` (about 2 KB) keeps the three rules the old gate file existed for: never auto-open, a
56px launcher inside the safe area on phones with a full-screen panel, and no chat bytes until the visitor hovers or
taps (the chat is then warmed in idle time). The launcher is a 56px indigo button with the Deep mark (labelled "Open the Deep assistant" for screen readers).

There is no iframe any more. On the first tap the loader fetches `static/deep-assistant.js`, a dependency-free web
component, and mounts `<deep-assistant mode="launcher">` in the page itself. Shadow DOM keeps the site's CSS and
the chat's CSS apart; the chat inherits the site's font; keyboards and scrolling behave on phones. The site can
also open it from any link: `window.deepAssistant.open()` or `window.deepAssistant.ask('What is ChampGraph?')`.
Optional attributes on the script tag: `data-theme="light|dark|auto"` (default light), `data-title`, `data-subtitle`,
`data-suggestions="a|b|c"`, `data-delay="3000"`, `data-quick-replies="a|b|c"`, `data-no-greeting`.
Test page: `/site`; the assistant itself at `/`; the old standalone page at `/legacy`; component reference:
`docs/WIDGET.md`. Cache-busting: include the script with `?v=<version>` (the version is in `/healthz`); the loader
forwards it to the component import.

### Proactive greeting (bubble + quick replies + badge)

A few seconds after load (`PROACTIVE.delayMs`, default 3000) a rounded card floats above the `ask` button:
the Deep mark, "Hi! I'm Deep 👋", a one-line offer, and "Deep • just now". Under it, up to four pill buttons
with common asks, right-aligned, sized to their text, fading in one after another (no motion under
`prefers-reduced-motion`). The button shows a red "1" badge while the card is visible. Tapping the card opens the
chat on its welcome screen; tapping a pill opens the chat and sends the pill's text as the visitor's first message
through the normal flow, except booking pills ("Book…", "Schedule…"), which open the in-chat booking card directly. The × dismisses it; dismissing or opening the
chat hides it for the rest of the session (`sessionStorage` key `dh_greeting_dismissed`). On phones it keeps
inside the viewport (`max-width: calc(100vw - 32px)`) and sits just above the button.

**Where to edit:** the `PROACTIVE` object at the top of `static/widget.js`: `title`, `question`, `message`
(optional intro line for the welcome screen; empty keeps the component's default), `quickReplies`, `delayMs`, `botName`, `unread`. Per-page overrides without touching
the file: `data-delay`, `data-quick-replies`, `data-no-greeting` on the script tag. From the site's own JavaScript:
`window.deepAssistant.greet()` shows it again, `window.deepAssistant.config` is the live config.

## Verify after deploy

* Open deependhq.com on a phone: one indigo Deep button bottom right, nothing auto-opens.
* Tap it: the chat fills the screen, answers "what is ChampGraph?" with a source link, and "book a call" shows the
  three call types.
* Browser dev tools → Application → Cookies: none from the assistant origin.
* `curl -I https://assistant.deependhq.com/healthz` returns 200.
