# Champ Robin Chat Widget

Intercom-style chat messenger for any website. It is a single script with no dependencies and no build step. It renders inside a Shadow DOM, so the host site's CSS can't break it and its CSS can't leak into the host site.

`index.html` is the production embed: the script and one `Robin.init()` pointing at the deep-agent server. The widget has no built-in sample content: answers, quick starts, booking, the privacy link and pop-ups all come from the backend (or from what you pass to `Robin.init`). Without a backend it says it isn't connected and logs a warning. The visual system (tokens, type, spacing, motion) is in [DESIGN.md](DESIGN.md).

## Features

| Feature | Where |
|---|---|
| Intercom-style side widget with **Home** and **Messages** tabs | `renderHome`, `renderMessages`, `tabs` |
| Window states **hidden → half → full**, plus a wide view, stepped with chevron up / down | `setMode`, `expand`, `collapse`, `stepper` |
| No email ask on open; up to **three quick-start buttons** (yours, or the server's most-asked questions) | `starters` config, `renderHome` |
| Connects to the **deep-agent** backend (answers with sources, booking, hand-over, history, outreach, speech) | `deepAgent` config, `DeepAgentAdapter` |
| Replies, **lead forms** (name, email, company) and **meeting slots** render inside the chat | `block_*` renderers |
| **Settings** for the visitor: light / dark / device, a brand colour, text size and reduce motion, with a live preview | `renderSettings` |
| **Search** across past chats on the Messages tab; a **chat history sidebar** in the wide view | `messageSearch`, `historySide` |
| Analytics events for every question asked, so the starters can later be swapped for the most-asked questions | `question_asked` / `starter_click` events |
| Input box modelled on deependhq.com: **+** menu (attach documents, emoji, dictate) and a **voice** conversation | `composer`, `startDictation`, `startVoice` |

There are no Help or News tabs. Add them to `tabs()` if you need them.

## Embed

```html
<script src="robin-widget.js"></script>
<script>
  Robin.init({
    deepAgent: 'https://assistant.deependhq.com',   // or endpoint: '/api/robin/chat', or adapter: {...}
    primaryColor: '#F4A62A',
    companyName: 'Your company',   // optional: "Hi, I'm Champ Robin from Your company"
    // starters: [{ label: 'Your question', value: 'your_value', icon: 'help' }],   // optional; else the server's
    onEvent: (e) => analytics.track('robin_' + e.type, e)
  });
</script>
```

You can also do it Intercom-style: set `window.RobinSettings = {...}` before the script loads, and the widget boots on its own.

## Use it in any framework

`robin-widget.js` is one plain JavaScript file with no dependencies. It draws everything inside its own Shadow DOM, attached to `document.body`, so the host app's CSS can't reach it and it doesn't affect the app's styles.

- **Script tag:** it sets `window.Robin`.
- **Bundlers** (Vite, webpack, esbuild, Rollup, Angular CLI, Next.js, Nuxt, SvelteKit): it is also a module.
  - `import Robin from 'robin-widget'` and `require('robin-widget')` both work.
  - TypeScript types ship in `robin-widget.d.ts`.
- **Server-side rendering:** importing it on the server is safe. Without a browser it returns the same API, and every call does nothing.

There is one widget per page. The rules are the same in every framework:
- Call `Robin.init(config)` once the app is in the browser, in a mount hook.
- Call `Robin.destroy()` when the component unmounts.
- Calling `init` again replaces the earlier widget, so React StrictMode's double mount and route changes are fine.

**Install.** Copy the folder into your project, or install it from the folder:

```bash
npm install ./robin-widget
```

**React** (Vite, CRA):

```jsx
import { useEffect } from 'react';
import Robin from 'robin-widget';

export function ChatWidget() {
  useEffect(() => {
    Robin.init({ endpoint: '/api/robin/chat', primaryColor: '#F4A62A' });
    return () => Robin.destroy();
  }, []);
  return null;   // the widget draws itself; render <ChatWidget /> once, e.g. in App
}
```

**Next.js** (App Router): put the component above in a file that starts with `'use client'`. Render it once in `app/layout.tsx`. For the Pages Router, render it in `_app.tsx`.

**Vue 3 / Nuxt 3:**

```vue
<script setup>
import { onMounted, onBeforeUnmount } from 'vue';
import Robin from 'robin-widget';
onMounted(() => Robin.init({ endpoint: '/api/robin/chat' }));
onBeforeUnmount(() => Robin.destroy());
</script>
<template><span /></template>
```

In Nuxt, you can also name the file `ChatWidget.client.vue` so it only renders in the browser.

**Angular:**

```ts
import { Component, OnDestroy, OnInit } from '@angular/core';
import Robin from 'robin-widget';

@Component({ selector: 'app-chat-widget', standalone: true, template: '' })
export class ChatWidgetComponent implements OnInit, OnDestroy {
  ngOnInit() { Robin.init({ endpoint: '/api/robin/chat' }); }
  ngOnDestroy() { Robin.destroy(); }
}
```

- With Angular SSR, `Robin.init` does nothing on the server and runs in the browser.
- If the CLI warns about a CommonJS dependency, add `"robin-widget"` to `allowedCommonJsDependencies` in `angular.json`.
- Alternatively, list `robin-widget/robin-widget.js` under `scripts` in `angular.json` and use `window.Robin`.

**Svelte / SvelteKit:**

```svelte
<script>
  import { onMount } from 'svelte';
  import Robin from 'robin-widget';
  onMount(() => {
    Robin.init({ endpoint: '/api/robin/chat' });
    return () => Robin.destroy();
  });
</script>
```

In SvelteKit, `onMount` only runs in the browser, so this is SSR-safe as written. Put it in `+layout.svelte` to have it on every page.

**Anything else** (Solid, Preact, Astro, Ember, jQuery, a CMS or plain HTML):
- Load the script tag and call `Robin.init()`, or set `window.RobinSettings`.
- In Astro, use a `<script>` in a layout, which runs in the browser.

**Good to know:**
- Fonts load from Google Fonts. Pass `loadFonts: false` to use the system fonts, for example under a strict Content Security Policy.
- **Content-Security-Policy.** The widget's styles are a `<style>` inside its Shadow DOM and some elements carry inline `style` values, so `style-src` needs `'unsafe-inline'`. Also allow: `img-src data: blob: https:` (the logo mask, image previews, GIFs, answer cards), `media-src blob:` (server text-to-speech), `connect-src` for the backend, `script-src` for the backend's origin (answer cards load its `/static/deep-ui.js`, which runs in the page, so only point `deepAgent` at a server you trust), and `fonts.googleapis.com` / `fonts.gstatic.com` while `loadFonts` is on (`loadFonts: false` skips Google Fonts).
- It sits at `z-index` 2147483000 by default; change it with `zIndex`.
- Settings choices and chats are saved in `localStorage` under `robin-widget:v1`. Pass `persist: false` to keep them only while the page is open. A dismissed teaser is remembered in `sessionStorage` for the browser session.

### Config

| Option | Default | Notes |
|---|---|---|
| `appName` / `companyName` | `Champ Robin` / none | `appName` appears in the header, intro, teaser, voice call and labels. `companyName` is optional: when set, the intro says "Hi, I'm Champ Robin from <companyName>" |
| `primaryColor` | `#F4A62A` (deependhq.com marigold) | The site's colour on the launcher and buttons. Text colour on it (black or white) is picked automatically for contrast. A brand colour the visitor picks in Settings replaces it and also colours the swallow and accents |
| `position` | `right` | `left` or `right` |
| `colorScheme` | `light` | `light`, `dark` or `auto` (follows the device). The visitor can also change it in Settings |
| `loadFonts` | `true` | Loads Bricolage Grotesque and Figtree from Google Fonts; set to `false` to use system fonts |
| `openingTransition` | `true` | Clicking the launcher opens the chat with a loading layer inside it (the particle loader in the middle), then fades to reveal the chat as its content rises in. The page is never covered. `false` opens straight away (reduced-motion visitors always do) |
| `thinkingOverlay` | `true` | While a reply is prepared, a blurred layer covers the chat window (not the page), with the large animated loader, the status and a **Stop** button in its middle. It lifts as soon as the answer (or streamed text) arrives. `false` shows a smaller loader in the thread instead |
| `placeholder` | `What would you like to know?` | Placeholder of the conversation input |
| `thinkingText` | `Thinking` | Loader status shown until the backend reports a more specific step |
| `disclaimer` | `AI responses can make mistakes. Check important info.` | One short line under the conversation input. With `privacyUrl` set it reads "By chatting with us, you agree to our Privacy Policy" (linked) instead |
| `motion` | `auto` | `auto` turns all animation off when the device asks for reduced motion (on Windows, when **Animation effects** is off). `full` always animates; `reduce` never does. The visitor's **Reduce motion** switch in Settings overrides this |
| `greeting` / `intro` | | Header copy |
| `attachments` | PDF, Office, CSV, TXT and images; 5 files; 10 MB each | `{ accept, maxFiles, maxSizeMB }`, or `false` to remove "Attach a file" |
| `emoji` / `dictation` / `voice` | `true` | Turn each input feature on or off |
| `voiceLanguages` | `['auto', 'en-US', 'hi-IN']` | Languages the Language button cycles through on the call screen and that dictation uses. `auto` uses the browser's language |
| `privacyUrl` | `null` | When set, the line under the input reads "By chatting, you agree to our Privacy Policy" |
| `starters` | `[]` | Your own quick starts (`{ label, value, icon }`); with a deep-agent server and none set, its most-asked questions. Only the first 3 show |
| `teaser` | `{ text, delay: 5000 }` | Small bubble beside the launcher; `null` disables it. Dismissal lasts for the browser session |
| `initialMode` | `hidden` | `hidden`, `half` or `full` (`peek` is still accepted and opens `half`) |
| `deepAgent` | `null` | URL of a deep-agent server (e.g. `https://assistant.deependhq.com`). See [Connect to deep-agent](#connect-to-deep-agent) |
| `schedulerUrl` | `null` | An external booking page, offered in Help & contact. A deep-agent server supplies its own |
| `visitorToken` | `null` | deep-agent: a signed-in visitor's token, minted by your server and sent as `X-Visitor-Token`. The server then knows who is talking and the forms prefill. Change it later with `Robin.setToken()` |
| `userName` / `userEmail` | `null` | deep-agent: unverified name and email hints for a visitor without a token |
| `endpoint` / `headers` | `null` | Backend URL. See the contract below |
| `adapter` | `null` | Custom transport `{ send(payload, opts) => Promise<{blocks}> }` (see [Loading, streaming and stop](#loading-streaming-and-stop)) |
| `persist` | `true` | Saves conversations, visitor details and Settings choices in `localStorage` |
| `onEvent` | `null` | Analytics hook (see Events) |

### JS API

`Robin.version`, `Robin.instance`, `Robin.HttpAdapter`, `Robin.DeepAgentAdapter`, `Robin.open(mode)`, `Robin.close()`, `Robin.toggle()`, `Robin.expand()`, `Robin.collapse()`, `Robin.setWide(true|false)`, `Robin.ask(text)`, `Robin.voice()`, `Robin.endVoice()`, `Robin.setScheme('light'|'dark'|'auto')`, `Robin.setBrand('#4A7BF7'|null)` (`null` restores the default look), `Robin.setTextSize('s'|'m'|'l')`, `Robin.setReduceMotion(true|false)`, `Robin.setToken(token|null)`, `Robin.on(type, fn)`, `Robin.reset()`, `Robin.destroy()`.

### Help & contact and transcripts

- **Help & contact** (the **?** button in the Home and Messages headers, and the conversation's title menu) is a Settings-style screen with: Book a meeting, Talk to a person, Voice conversation (when the browser can listen), the booking page (`schedulerUrl`, or the deep-agent server's own scheduler link), common questions (the starters, without the ones that only book or reach the team), and what the chat keeps, with the privacy link and the last conversation to download.
- **Download transcript** (the conversation's title menu) saves the conversation as a `.txt` file: who said what and when, with the choices, forms, times, bookings and links written out. It is built in the browser; nothing is sent anywhere.

## Window states

Clicking the launcher (or the teaser) opens **half**. The header shows one chevron: **⌃** at half height, **⌄** at full height. ✕ (or Esc, or the launcher) closes the chat.

| State | What it shows | ⌃ goes to | ⌄ goes to |
|---|---|---|---|
| **hidden** | Launcher only (plus the optional teaser) | | |
| **half** | The messenger at half-screen height: Home and Messages tabs, conversation thread, Settings | full | (not shown; ✕ closes) |
| **full** | The same messenger at full viewport height. The launcher is hidden, so use ⌄ or ✕ | (hidden) | half |
| **wide** (full + expand) | Inside a conversation only, the **expand icon** (⤢) next to the chevrons widens it to half the screen at full height; the thread and input stay a centred, readable column. Press it again (⤡) to go back to normal width. From half it jumps straight to wide | (hidden) | half |

- There is no compact "peek" card any more. `open('peek')` and `initialMode: 'peek'` still work and open **half**, so older embeds don't break.
- Going between half, full and wide only resizes the panel. The open thread and half-typed form fields are kept, and a thread scrolled to its latest message stays there while the panel resizes.
- The expand icon shows only in an open conversation, not on Home, Messages or Settings, and only on screens 900px and wider (half the screen is no wider than the normal panel below that). Leaving the conversation, closing or shrinking the messenger turns wide off, and `Robin.setWide(true)` does nothing outside a conversation.
- On phones (≤480px) every state is a bottom sheet (half 62% of the screen, full the whole screen), with a grab handle that also steps the size. The launcher is hidden there while the sheet is open; ✕ closes it.

## Input box

The input box copies deependhq.com's: one rounded box holding **+**, the text field, a voice button and send.

- **+ menu** (the + turns into an × while it's open):
  - **Attach a file**: opens the file picker. Files can also be dragged onto the box or pasted. Each file shows as a chip with a thumbnail (images) or a type badge, its name and size, and a remove button. Files that are too big or of an unsupported type show in red and aren't sent.
  - **Emoji**: a searchable picker above the input. Clicking an emoji inserts it at the cursor, and the picker stays open so you can add more.
  - **Dictate**: speech appears in the text field as you talk, with a red dot, a level meter and a timer. ✓ keeps the text and × restores what was typed before. Nothing is sent until you press send.
- **Voice button** (waveform): starts a spoken conversation on a full-panel call screen. Robin listens, sends what it heard as a normal message (`input.via = "voice"`), reads the reply aloud with captions, then listens again.
  - The orb reacts to your microphone level. Tap it to interrupt Robin.
  - Controls: **Mute**, **End call**, **Captions** and **Language**.
  - The ⌄ button minimises the call to an "In a call · Return · End" bar above the chat. Closing the widget ends the call.
  - If a reply contains a form or time slots, Robin says "I've put the details in the chat."
- **GIF** (in the + menu, with a deep-agent server that has a GIF key): a searchable grid; choosing one sends it, and it shows as the image.
- **Browser support**: dictation and voice use the browser's built-in speech recognition (Chrome, Edge and Safari; Firefox doesn't have it). Where it's missing, those options are greyed out with a note. In Chrome, speech recognition sends the audio to Google's speech service. Mention that in the privacy policy, or swap in a server-side speech-to-text later. The microphone only works on `https://` or `localhost`.

## Connect to deep-agent

Set `deepAgent` to the server's URL and Robin uses the deep-agent backend for everything a visitor does. The backend is used as it is, through its public API; nothing in it needs to change.

```js
Robin.init({ deepAgent: 'https://assistant.deependhq.com' });
```

**The one server setting:** the page's origin must be in the server's `ALLOWED_ORIGINS` (its `.env`), or the page must be served by the server itself. `http://localhost…` pages are always allowed in local development. `index.html` shows the setting: `deepAgent: 'https://assistant.deependhq.com'`.

| deep-agent API | What Robin does with it |
|---|---|
| `GET /healthz`, `GET /widget-config`, `GET /me` | On start: checks the server is up (an offline badge and note if not); takes the privacy link, quick starts (the most-asked questions), upload types and size, voice languages, GIF and server-speech switches; a returning visitor's "Welcome back" line on Home; name, email and company to prefill forms. What the site sets in `Robin.init` always wins |
| `POST /track` | The session beacon, once per conversation (page, referrer, timezone, language, screen) |
| `POST /chat` (server-sent events) | Every question. The status steps drive the loader's line and the swallow's state (searching → the magnifier, writing → typing). The answer streams in; `[n]` markers become links to their sources, which also show as chips under the answer. Booking steps (call types, the time grid, a reviewed slot) become buttons, the time picker and the details form. A hand-over offer becomes "Talk to the team" and "Book a meeting" |
| `POST /conversations/{id}/title` | After the first answer: the 3–6 word title the server writes, for the Messages list and the sidebar |
| `POST /feedback` | 👍 / 👎 on an answer, with the server's message id. A 👎 asks what went wrong (reason chips and an optional note) and sends that as the rating's `note` |
| `ui` events on `/chat`, `GET /static/deep-ui.js` | **Answer cards**: a table, figures, steps or next-step buttons the server sends under an answer, drawn by the server's own renderer (loaded once, on the first card) as text only, in Champ Robin's colours. A card button asks its label or opens a page the server allows |
| `GET /conversations`, `GET /conversations/{id}`, `POST …/read`, `PATCH /conversations/{id}` | Messages lists the visitor's server conversations too (another device when signed in), with an unread dot; opening one loads its history and marks it read; "Rename conversation" in the title menu renames it (in the widget's own rename dialog) |
| `GET /booking/availability`, `POST /booking/confirm` | "Book a meeting": call types, open times in the visitor's timezone, the details form ("Confirm booking"), then the confirmation with Join Zoom, Add to calendar and Manage booking. A taken slot shows the nearest open times again |
| `GET /bookings`, `POST /booking/{id}/reschedule`, `DELETE /booking/{id}` | Home's "Your bookings": each upcoming call with Join, Add to calendar, Reschedule (new times, in the chat) and Cancel (after the widget's own "Cancel this booking?" confirmation) |
| `POST /handover` | "Talk to the team": name, email and the question; the team replies by email |
| `POST /upload` | Files attached to a message are uploaded first and sent with it |
| `GET /gifs` | The GIF picker |
| `POST /tts`, `POST /stt` | When the server has speech: Read aloud and the voice call's replies use the server's voice; dictation uses server transcription in browsers without speech recognition |
| `POST /outreach/check`, `POST /outreach/event` | The teaser follows the owner's outreach rules (title, message, replies, re-checked as the visitor reads); tapping or dismissing it is reported, and the chat it opens carries the pop-up's id |
| `POST /ask/claim` | A booking email's "Ask" link (`#ask-deep=…` on the site, or `#t=…` on `/ask`) opens the chat it was sent for, with its questions as chips and the chosen one sent at once. The token is removed from the address bar |

**Not used by the widget, on purpose:** the owner console (`/admin/*`) and the server's own pages (booking manage and cancel pages, the host booking page, outcome and opt-out pages, `/`, `/site`, `/demo`). Robin links to the manage and calendar pages where a visitor needs them.

**Headers:** with `deepAgent`, keep custom `headers` to the ones the server's CORS allows (`X-Visitor-Token` for a signed-in visitor); any other header makes the browser refuse every request.

**Sessions and ids:** each Robin conversation is one deep-agent session (`X-Session-Id`). A random visitor id is kept in `localStorage` (`robin-widget:visitor`) and sent as `X-Visitor-Id`, so the server's memory, history and bookings recognise a returning browser.

**Sanitizing:** everything typed is cleaned before it is shown or sent. Control characters and hidden text-direction marks are removed, long runs of blank lines are cut, and each field is capped at the server's own limits (message 4000, name 120, email 200, company 120, notes 1000, hand-over message 2000, title 80). Links from the server or an answer only open if they are `http(s)` or `mailto`, GIFs only from `https`.

## Backend contract

The widget `POST`s JSON to `endpoint` and expects a list of **UI blocks** back. This block list is the seam for OpenUI: the backend (or the OpenUI layer) decides *what* to render, and the widget decides *how*.

### Request

```jsonc
{
  "conversationId": "conv_ab12…",
  "visitor": { "name": "…", "email": "…", "company": "…" },   // empty until a form is submitted
  "input": { "type": "message", "text": "Do you integrate with HubSpot?", "via": "text" },   // via: "voice" for spoken turns (keep replies short)
  // with files: "input": { "type": "message", "text": "…", "attachments": [{ "id", "name", "size", "type" }] }
  // or an action from a block:
  // { "type": "action", "name": "starter",     "value": "book_demo", "label": "Book a demo" }
  // { "type": "action", "name": "button",      "value": "pricing",   "label": "Pricing & plans" }
  // { "type": "action", "name": "submit_lead", "data": { "values": {name, email, company}, "context": {…} } }
  // { "type": "action", "name": "select_slot", "data": { "start": "2026-10-20T06:00:00.000Z", "durationMinutes": 20, "context": {…} } }
  "history": [{ "role": "user" | "bot", "text": "…" }],          // last 20 messages, text only
  "page": { "url": "…", "title": "…" }
}
```

### Response

```jsonc
{ "blocks": [
  { "type": "text", "text": "Supports **bold**, `code`, [links](https://…), newlines,\n- bullet lists\n1. and numbered lists" },
  { "type": "buttons", "options": [{ "label": "Book a demo", "value": "book_demo" }, { "label": "Docs", "url": "https://…", "icon": "external" }] },
  { "type": "lead_form", "title": "Get a quote", "hint": "…", "submitLabel": "Send",
    "context": { "intent": "pricing" },
    "fields": [{ "name": "name", "label": "Name", "required": true },
               { "name": "email", "label": "Work email", "type": "email", "required": true },
               { "name": "company", "label": "Company", "required": true }] },
  { "type": "time_slots", "title": "Demo call", "durationMinutes": 20,
    "context": { "calendar": "sales" },
    "slots": ["2026-10-20T04:30:00Z", "2026-10-20T06:00:00Z"] },
  { "type": "card", "title": "…", "text": "…", "image": "https://…", "cta": { "label": "Read more", "url": "https://…" } },
  { "type": "confirmation", "title": "You're booked!", "lines": [{ "icon": "calendar", "text": "Tue, Oct 20 · 10:00 AM" }, { "icon": "mail", "text": "Invite sent to …" }] }
]}
```

- **Icons:** buttons, starters, form fields, forms (`icon` on the block) and confirmation lines take an optional `icon` name. Available names: `help`, `calendar`, `tag`, `headset`, `check`, `user`, `mail`, `building`, `phone`, `clock`, `messages`, `trending`, `external`, `sparkles`, `lock`, `alert`. If you leave it out, buttons pick one from their `value` (`book_demo` → calendar, `pricing` → tag, `contact` → headset, `about` → help), fields from their `name` (name → user, email → mail, company → building), and link buttons get `external`. Confirmation `lines` can be plain strings or `{ icon, text }`.
- **Files:** when a message has attachments, the request is `multipart/form-data` instead of JSON. The usual JSON goes in a `payload` field, and each file goes in a `files` part.
- `context` on a `lead_form` or `time_slots` block is echoed back with the submit or select action, so the backend can stay stateless between steps.
- Slots are ISO timestamps. The widget groups them by day and shows them in the visitor's timezone.
- Unknown block types that have a `text` field render as text; others are dropped.
- If the request fails, the widget stops the loader and shows an inline **Retry** that re-sends the same input.
- Keep model calls and API keys on the server side of this endpoint. The widget never holds a key.

### Loading, streaming and stop

While a reply loads, the conversation shows the dotted-cross loader with a status line under it, and the send button becomes **Stop**. The status says `thinkingText` ("Thinking") until the transport reports what it is actually doing. The widget never cycles through made-up progress messages.

`send(payload, opts)` receives:

| `opts` | Use |
|---|---|
| `signal` | An `AbortSignal`. **Stop** aborts it. The HTTP adapter passes it to `fetch`, so the request is cancelled. |
| `onStatus(text)` | Report the current step, such as `'Searching the docs…'` or `'Checking availability…'`. Each call fades the status line to the new text. |
| `onText(text)` | Streaming: call it with the answer so far, as it grows. The answer replaces the loader and grows in place, and the final `blocks` take over without a jump. |

Pressing Stop keeps any text that has already streamed in as the reply, notes "Response stopped", and fires a `reply_stopped` event. The built-in HTTP adapter doesn't stream. Write a custom `adapter` to use `onStatus` and `onText` with your backend (SSE, a websocket, or an SDK).

## Events

`onEvent(e)`, `Robin.on(type, fn)` and a `robin:event` DOM event all receive the same payload: `{ type, at, …data }`.

| type | data |
|---|---|
| `open`, `close`, `mode_change` | `mode`, `from` |
| `scheme_change` | `scheme` |
| `teaser_shown` | |
| `starter_click` | `label`, `value` |
| `question_asked` | `text`, `conversationId`, `via` (`text` or `voice`). Use this to find the most-asked questions for the starters |
| `files_added`, `files_sent` | `count` |
| `emoji_open`, `gif_open` | |
| `backend_offline` | (the `deepAgent` server didn't answer at start) |
| `dictation_start`, `dictation_end` | `lang` / `kept` |
| `voice_start`, `voice_mute`, `voice_end` | `lang` / `muted` / `seconds` |
| `lead_submitted` | `values`, `context` |
| `slot_selected` | `start`, `context` |
| `brand_change` | `color` (`null` for the default look) |
| `text_size_change` | `size` (`s`, `m` or `l`) |
| `motion_change` | `reduce` |
| `wide_change` | `wide` (true when expanded to half the screen) |
| `reply_stopped` | `conversationId`, `partial` (true if some text had already streamed in) |
| `response_feedback` | `conversationId`, `messageId`, `value` (`up`, `down`, or `null` when cleared) from the 👍 / 👎 under an answer; after a 👎, again with `note` (the reasons and text the visitor gave) |
| `transcript_download` | `conversationId` |
| `answer_card`, `answer_card_button` | `state` (`rendered` or `dropped`) / `label` |

## No backend set

`Robin.init()` without `deepAgent`, `endpoint` or `adapter` shows no invented content. The presence shows offline, a message gets "This chat isn't connected yet", and the console warns `[Robin] No backend is set`.

## Open items

- Human handoff: when a person takes over a chat, show their name and photo there (Robin's own answers keep the swallow).
- Arrow-key movement inside the tabs and option groups (Tab and Enter work today).
