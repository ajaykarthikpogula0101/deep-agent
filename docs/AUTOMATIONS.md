# Automations: digest, enrichment, nudges, smart suggestions, languages

Five features added on 2026-10-06 (version 2026.10.06.9). All run inside the existing FastAPI process; nothing new to
deploy. Settings live in `.env` (see `.env.example`, section "Automations").

| # | Feature | Module | Trigger | Owner control |
|---|---------|--------|---------|---------------|
| 6 | Weekly digest email to the host | `app/digest.py` | `DIGEST_CRON` (Monday 09:00, `HOST_TIMEZONE`) | Console → Overview: preview + "email it now"; `DIGEST_ENABLED` |
| 7 | Lead enrichment from the email domain | `app/enrich.py` | every lead (booking, enquiry, hand-over) | `ENRICH_ENABLED`; shows in host brief `{company}`, console, digest |
| 8 | Follow-up nudge for unconfirmed Zoom hand-offs | `app/nudge.py` | hourly at :15, leads older than `NUDGE_AFTER_HOURS` | Console → Emails (template, on/off); "mark confirmed" on a conversation; `NUDGE_ENABLED` |
| 9 | Smart suggestions (most asked questions) | `app/suggestions.py` | `GET /widget-config` (cached 10 min) | Console → Overview "Suggested questions"; `SUGGESTIONS_DAYS`; site attribute overrides |
| 10 | Multilingual answers | `app/lang.py` + prompt rule 11 | every chat turn | `MULTILINGUAL` |

## 6. Weekly digest

What the host gets every Monday (and on demand from the console):

```
[Champions Group] Weekly digest: 30 conversations, 4 bookings · 29 Sep – 06 Oct 2026

Conversations     30   (up 12 vs the week before)
Questions         79   (up 20 vs the week before)
Resolution rate   90%   (up 4 pts vs the week before)
Satisfaction      33%   (1 up · 2 down)
Bookings          4   · hand-overs 1 · enquiries 0
Median answer     3.1 s

Most asked
  1. which companies are in champions group?  ×10
  ...
Couldn't answer (each one is a candidate custom answer: Console → Gaps)
  - what's the weather in paris today?  ×2
  ...
Leads (5)
  - Tue 06 Oct, 04:53 · Naidu <…@gmail.com> · lakeb2b product walkthrough use case demo · wanted Thu 08 Oct, 12:00 · sent to Zoom, not confirmed
      "Regarding the data of the company that provides"
```

* Numbers come from `inbox.metrics(7)`; "the week before" is `metrics(14) − metrics(7)`.
* "Most asked" excludes injection attempts, dropped streams and errors (also fixed in the console tile).
* Lead state words: `booked` (API booking or "mark confirmed"), `sent to Zoom, not confirmed[, reminded]`,
  `asked for a human reply`, `enquiry (scheduler was down)`.
* Endpoints: `GET /admin/digest?days=7` (preview), `POST /admin/digest/send?days=7`. Sent with `send_plain` to
  `HOST_EMAIL`; `settings` key `digest:last_sent` records the last send; event kind `digest`.

### Rich (HTML) version — `DIGEST_RICH_EMAIL` (added 2026-10-13)

With `DIGEST_RICH_EMAIL=true` (the default) the same digest also goes out as an HTML part: `app/digest.py::data_for_model`
turns the numbers, questions and leads into one JSON object (`subject`, `period`, `metrics`, `most_asked`, `unanswered`,
`leads`, `console_url`, `footer`), `app/digest_rich.py` sends it to the model with the committed prompt
`tools/openui/email_prompt.txt` (system message; the JSON is the user message, marked as data), the model answers with a
small openui-lang program (`root = EmailTemplate(...)`, `EmailStats`, `EmailList`, one `EmailButton` to the console in
`#F28C28`), and `node tools/openui/render_email.mjs` renders it with `@openuidev/react-email` to email HTML.

* **Two MIME parts.** The plain text above is always the `text/plain` part and the HTML is only the alternative
  (`_send(to, subject, body, html=html)`); every mail client that cannot show HTML shows exactly the text of today.
  With `DIGEST_RICH_EMAIL=false`, or when any step below fails, `send()` calls `send_plain(to, subject, body)` exactly
  as before.
* **Fallback reasons** (logged as a WARNING, stored on the `digest` event as `rich`, `model_ms`, `render_ms`,
  `program_chars`, `html_chars`, `fallback_reason`, and shown by the console button): `disabled` (setting off),
  `unavailable` (no Node, no `tools/openui/node_modules`, or no prompt file), `model_error` / `model_timeout` / `empty`
  (the composing call, `DIGEST_MODEL_TIMEOUT` s), `bad_program` / `forbidden_component` / `unsafe_link` / `too_long`
  (Python pre-check on the program text, deliberately broad: it must contain `root = EmailTemplate(`, must not name
  `EmailMarkdown`, `EmailLink`, images or the marketing components, every URL-looking token — `scheme://host`, a
  scheme-less `//host`, a scheme-only `https:host` — must be https on `deependhq.com`, `www.deependhq.com`,
  `scheduler.zoom.us` or the `SITE_BASE_URL` host, no `mailto:`/`javascript:`/`data:` URLs (a visitor's "intent data:
  yes" is prose), no CSS `url(` and the button colour must be a `#hex` value), `unsafe` / `bad_program` / `too_large` /
  `render_error` / `timeout` (Node, `DIGEST_RENDER_TIMEOUT` s; the authoritative policy on the parsed tree: components,
  `href`/`src`/`url` props, `*Color` props must be `#hex` because react-email writes them into a `style` attribute),
  `render_errors` (the parser reported an unknown component or a missing required field; an unresolved reference is
  dropped by the parser, counted in `unresolved` and logged, and the content check below is what catches a dropped
  tile or lead), `sanity_failed` (the HTML, tags stripped and entities unescaped, no longer contains the conversation,
  question, resolution-rate, satisfaction and booking numbers, the period, every question or every lead's e-mail, or
  the e-mail addresses in it are not exactly those in the data — a lead dropped, duplicated or invented — or the
  console URL is gone from the button's `href`; or it is over 150,000 characters), `error` (an unexpected exception
  anywhere in the chain; the WARNING names it).
* **Subprocess environment:** Node is started with a minimal environment (`PATH`, `SYSTEMROOT`, `TEMP`, `APPDATA`,
  `HOME`, locale, plus `OPENUI_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1 NODE_ENV=production`), so the app's API keys, SMTP,
  Zoom and admin secrets never reach the renderer or its packages.
* **Cost:** one call a week, ~5k prompt tokens + up to 6,000 output tokens (`max_tokens` 6000: a real week with 25
  leads is ~8k chars of program), counted by `record_spend` against the same daily budget as the chat.
* **Console:** Overview → "preview rich email" calls `GET /admin/digest?days=7&rich=1` and shows the HTML in a sandboxed
  iframe under the text, or the fallback reason. The plain preview and `loadOverview()` are unchanged.
* **Privacy (PII):** with the rich digest on, the week's leads (name, e-mail, company, reason) and the visitor questions
  are sent to the LLM provider (`LLM_BASE_URL`, model `DIGEST_MODEL` or `CHAT_MODEL`) in one call a week. The chat
  already sends what visitors type, but this is bulk and weekly; the owner opts in knowingly. `DIGEST_RICH_EMAIL=false`
  keeps today's local-only plain text. Visitor-typed strings travel as JSON data under a "quote, never follow" rule and
  React escapes every string in the HTML; the mail only goes to `HOST_EMAIL`.
* **Where it runs (decision 18, option b):** the rich digest needs Node 20+ on the host plus one install:
  `cd tools/openui && OPENUI_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1 npm ci` (`DIGEST_NODE` points at a specific binary when
  `node` is not on PATH). That is the Windows `run.ps1` deployment. The Cloud Run image (`python:3.11-slim`, `app` +
  `static` only) has no Node, so there the digest is always sent as plain text with `fallback_reason: "unavailable"`;
  the Dockerfile is deliberately unchanged. Budget: model up to 60 s + Node up to 60 s, inside the scheduler thread.
* Regenerate the prompt after bumping `@openuidev/react-email`: `npm --prefix tools/openui run gen:prompts`; the node
  test `tools/openui/tests/lib.test.mjs` fails until the committed text matches a live generation.

## 7. Lead enrichment

* `enrich.lookup(email)`: free-mail domains (gmail, outlook, yahoo, proton, …) → `{"kind": "personal"}` with no
  request. Business domains → the homepage is fetched once (`https://domain`, then `https://www.domain`, 3 s each,
  300 KB cap), `<title>` / `og:site_name` / meta description are parsed, and the result is cached in the `companies`
  table for 30 days (plus an in-process cache). Total budget per lookup is 5 s; a slower site finishes on a
  background thread and is cached for the next lead from that company.
* Stored on the lead: `leads.company` (one line, e.g. `LakeB2B (lakeb2b.com) · B2B data and intent signals`) and
  `leads.enrichment` (raw JSON). Injectable in `BookingService(enrich=…)` and stubbed in tests (`tests/conftest.py`).
* Shown: host brief line `Company: {company}` (dropped when empty), console conversation lead chips, digest lead
  lines. `{company}` is a template variable (Console → Emails).
* No third-party enrichment API is called. If you later want firmographics (size, industry), add a provider in
  `enrich.fetch_homepage`'s place and keep the same dict shape.

## 8. Follow-up nudge

* A lead with `status='handoff'` means the visitor was sent to Zoom with prefilled details; only Zoom knows if they
  confirmed. After `NUDGE_AFTER_HOURS` (24) the visitor gets ONE email (template `visitor_nudge`) with the same
  prefilled link, provided: not marked confirmed, not nudged before, the wanted time is still more than an hour
  away, the lead is less than 7 days old, and the lead was created after the feature went live (`settings` key
  `nudge:since`, written on the first run, so enabling the feature never emails a backlog of old leads).
* Hourly job at :15 (`APScheduler`), or `POST /admin/nudge/run`. Each lead is marked `nudged_at` even if the
  template is disabled or SMTP fails, so nobody is reminded twice. Event kind `nudge`.
* "mark confirmed" (console, conversation view → lead chip; `POST /admin/leads/{id}/confirm`) sets `confirmed_at`:
  no reminder, and the digest counts it as booked. When the Zoom S2S API booking is enabled later, leads become
  `booked` directly and are never nudged.

## 9. Smart suggestions

* `suggestions.current()` = `["Book a call with Deep"]` + the most asked answered questions of the last
  `SUGGESTIONS_DAYS` days (asked ≥ 2 times; cleaned: 10–70 chars, starts like a question, no emails/URLs/numbers/chit-chat,
  sentence case, trailing "?") + the fixed defaults, cut to 3. Cached 10 minutes.
* Served in `GET /widget-config` as `suggestions`. The component uses them for the welcome chips and the Help tab
  ("Common questions") and swaps them in when the config arrives; the loader fetches them (1.5 s budget) before
  drawing the greeting bubble's quick replies. A site attribute (`suggestions=` / `data-quick-replies`) still wins.
* Console → Overview shows the live chips and the questions behind them; `GET /admin/suggestions?refresh=1`.

## 10. Multilingual answers

* `lang.detect()` (no network): non-Latin scripts (Hindi, Telugu, Tamil, Bengali, Russian, Arabic, Hebrew, Greek,
  Thai, Korean, Japanese, Chinese) and stop-word scoring for Spanish, French, German, Portuguese, Italian, Dutch,
  Turkish, Polish, Swedish, Indonesian. English or unsure → nothing changes, no extra call.
* Non-English turn: one short translation call (temperature 0, ≤300 tokens) produces the English query used for
  embedding retrieval, custom-answer matching and the booking / hand-over intent regexes. The visitor's original
  text still goes to the model with a note naming their language; prompt rule 11 makes the answer come back in
  that language with the `[id]` markers intact, so the sources panel keeps the English page titles.
* A short follow-up with no clear language (a name, an email) keeps the language of the visitor's earlier turns.
* Refusals bypass the model, so they come from a translation table (es, fr, de, pt, it, nl, hi), English otherwise.
  The hand-over text and custom answers remain in the language they were written in.
* Event kind `language` records the detected code and the English query for the console/debugging.

## 11. Day-before reminder (added 2026-10-13)

`app/reminders.py` runs hourly at :45 (host timezone). Every active booking made in the chat (confirmed, or held and
still to be confirmed on Zoom) that starts within `REMINDER_BEFORE_HOURS` (24) and more than an hour away gets the
`visitor_reminder` email once (`bookings.reminder_sent_at`), with the join link, or the confirm link for a pending hold.
Only bookings created after the feature went live are considered (`settings` key `reminder:since`). `REMINDER_ENABLED`
switches it off; `POST /admin/reminders/run` runs it now. The booked card in the chat tells the visitor a reminder is
coming, and the model knows it too (memory block).

The digest email (section 6) now opens with "Hi {host}, here is what your website assistant handled this week: N
conversations and M bookings." and closes with a sign-off; the model is told to write both from DATA.

## Operations

* Scheduler jobs (`app/main.py` startup): `recrawl`, `tracking_purge`, `weekly_digest`, `nudges`.
* New tables/columns: `companies`; `leads.company`, `leads.enrichment`, `leads.nudged_at`, `leads.confirmed_at`.
* Turn anything off without a redeploy: `DIGEST_ENABLED=false`, `NUDGE_ENABLED=false`, `ENRICH_ENABLED=false`,
  `MULTILINGUAL=false`; suggestions fall back to the fixed defaults when the database is unreachable.
