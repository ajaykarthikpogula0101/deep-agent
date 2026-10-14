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
| 12 | Pre-call brief + lead score for the host | `app/precall.py` | every booking in the chat; day-before (:45); hot leads hourly at :30 | Console → Bookings; `PRECALL_*`, `HOT_LEAD_*` |

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

## 12. Pre-call brief and lead score (added 2026-10-13)

Before every call Deep gets a one-page brief on the person, built from what the assistant already stores. No new key,
no paid data: `app/precall.py`.

**What is gathered** (`gather`): every chat session of the person: the booking's session, every session of the same
browser (visitor id), and every session whose lead, booking or sign-in has the same email. From those: the visits, the
questions they typed (greetings and booking commands such as "book a call" left out), the pages they opened the chat
on, channel and referrer, location (from the IP), questions the assistant could not answer, messages left for Deep,
earlier bookings and cancellations, the company read off their email domain (section 7), their booking note and guests.

**The score** (`score`, 0–100, fixed rules so every point is explained; base 10, no caps per group). Every rule
belongs to one of four groups, shown in the brief as `Profile:  Fit 4 · Intent 12 · Engagement 0 · Risk −13 (2 flags)`:

| Group | Signal | Points |
|---|---|---|
| risk (checked first) | staff or test address (`SCORE_INTERNAL_DOMAINS`, `SCORE_INTERNAL_EMAILS`, `HOST_EMAIL` with any +tag); a staff booking with an outside business guest is flagged instead | −50 |
| | test booking (note, name or company like "test booking", or 5+ bookings from the address) | −30 |
| | competitor address, booker or guest (`SCORE_COMPETITOR_DOMAINS`) · throwaway inbox (mailinator, yopmail, ...) | −20 · −20 |
| | domain one typo off a free-mail provider (gmial.com): scored as personal email, flagged | 0 |
| fit | company email / university email (.edu, .ac.xx, or the homepage says university or college) / personal email | +15 / +3 / 0 |
| | typed company matches the email domain or homepage · typed a company with a personal email (unverified) | +5 · +3 |
| | network matches the typed company / the email domain / another company's network (docs/TRACKING.md, `NET_SCORE`) | +10 / +5 / +3 |
| | guests: company emails +8, +2 each more; free-mail guests +4, +1 each more (max 15; the booker and staff not counted) · a personal-email booker brings a company-email guest | up to +15 · +5 |
| | target country (`SCORE_TARGET_COUNTRIES`, off by default) · 1–4 earlier calls that already took place | +5 · +5 |
| intent | call type (`SCORE_CALL_TYPES`: demo 10, GTM 8, discovery 0; unknown slugs by keyword, or 5 for 30+ minutes) | 0–10 |
| | asked about pricing, a trial or sample data, contracts and terms, implementation and timelines | +20 for the first topic, +5 each more (max 30) |
| | described the data they need (only when no buying topic) | +5 |
| | booking note: 2+ specifics (data, numbers, region or industry, timeline, buying words) / 1 specific or 8+ words | +10 / +5 |
| | call within 3 days / within a week · asked for a person · campaign / search · a key page (`SCORE_KEY_PAGES`) | +5 / +2 · +5 · +5 / +3 · +5 |
| engagement | questions typed: 6+ / 3–5 / 1–2 · visits: 3+ / 2 · 5+ minutes on the site | +15 / +10 / +4 · +15 / +8 · +3 |
| risk | personal email claiming a well-known brand nothing confirms (not when the network or a guest's domain does) | −10 |
| | placeholder company (xyz, n/a, -) · no real name · name and personal email differ | −5 · −5 · −3 |
| | call 3+ weeks out · cancelled before · missed a call before · moved this call | −3 · −10 · −10 · −3 |
| | asked about jobs · reads like a vendor pitch | −25 · −15 |
| | 0-point notes the learner can move: typed company differs from the email's, another upcoming call, typed instructions to the assistant, network kinds | 0 |

Risk rules that need a look (brand claim, placeholder, name, internal, competitor, ...) also add a **flag**: flags lead
the brief's WATCH OUT section, and the model may add one caution of its own. A company the visitor only typed is shown
as "says they are from X", never as fact; a business email's company is "from their website" only when the homepage was
actually read. Each brief keeps `at_booking`, the score as it was when they booked; refreshes never overwrite it.
Hot is 60+ (`HOT_LEAD_SCORE`), warm 35+, else cold.

**The written part** (`compose`): one model call (`PRECALL_MODEL`, default `CHAT_MODEL`; `PRECALL_MODEL_TIMEOUT` 25 s)
turns the facts into a 2–3 sentence summary, interests, talking points, questions to ask and watch-outs. The prompt
allows only the given facts (no invented titles, sizes or budgets), treats everything the visitor typed as data, and
asks for the name or "they", never a guessed gender. URLs are stripped from the reply. When the model is off
(`PRECALL_USE_MODEL=false`), slow or returns something unusable, a rule-based brief from the same facts is used, so a
brief always exists. Stored on `bookings.brief` / `bookings.brief_at`.

**Where Deep sees it**

* "New booking" email: the brief is appended and a hot or warm lead is named in the subject ("· Hot lead · 72/100").
  The visitor's and guests' emails go out at once; Deep's copy waits on a worker thread for the brief (about 10–30 s)
  and goes out without it if building fails. If the visitor moved or cancelled meanwhile, it says so at the top.
* "Brief for tomorrow" (or "for your call today") to Deep, rebuilt so later chats count, in the same :45 pass as the
  visitor reminder (`PRECALL_HOST_REMINDER`). Skipped for bookings made in the last 12 hours: their "New booking"
  email already carried it.
* Hot leads without a call: hourly at :30, anyone who left an email (hand-over, enquiry, sign-in), chatted in the last
  24 hours, has been quiet 30+ minutes, scores hot and has no booking gets one "Hot lead, no call booked yet" email to
  Deep with a follow-up brief and a reply button; at most once per 14 days per email, at most 5 per run
  (`HOT_LEAD_ALERTS`). Anonymous visitors are never alerted: there is nobody to follow up with.
* Console → Bookings: the score on every booking; open one for the full brief, "refresh brief", "email it to me",
  "open conversation". Below: everyone who left an email and has no call, scored, with "send hot-lead alerts now".

Endpoints: `GET /admin/bookings/{id}/brief[?refresh=1]`, `POST /admin/bookings/{id}/brief/email`,
`GET /admin/leads/scored?days=`, `POST /admin/leads/alerts/run`.

## 13. Knowledge-gap loop (added 2026-10-14)

Questions the assistant could not answer used to end up in a list. Now they come back as drafted answers that Deep
approves with one click; the assistant answers them from then on, and the people who asked get the answer by email.
`app/gaps.py`.

**Every night** (`GAP_CRON`, default 03:20 host time, after the re-crawl) the visitor questions of the last `GAP_DAYS`
(30) that were refused (low confidence) or marked "not helpful" are collected. Left out: greetings and small talk,
booking commands and the booking form's own messages, one-word fragments, and questions an existing custom answer now
covers. Each question joins the draft it matches (`GAP_SIMILARITY` 0.78 on the local embeddings: rewordings score
0.76–0.97, different questions up to 0.75) or starts a new group. The biggest new groups (`GAP_MAX_DRAFTS`, 10 a night)
get one model call each (`GAP_MODEL`, default `CHAT_MODEL`) with the site's six closest excerpts:

* the question in plain words, and an answer **only** from the excerpts; where the site is silent the draft says what is
  missing and leaves a `[placeholder]` for Deep's fact ("needs your facts" in the console, "answered from the site" when
  it is fully covered);
* off-topic questions (weather, homework), small talk and fragments that only made sense mid-conversation are
  dismissed automatically (Deep can restore them).

Without a model the draft is left for Deep to write. Each message is processed once (`gap_asks`).

**Console → Gaps → Drafted answers**: the question as visitors wrote it, the drafted question, answer and source link
(all editable), "Approve", "draft again", "dismiss", and the approved and dismissed lists. "draft new answers now" runs
the nightly job on demand.

**Approve** refuses an answer that still has a `[placeholder]`, then creates the custom answer: the question plus up to
four of the visitors' own wordings (so a reworded question hits it too), all with the same answer and link. From that
moment the assistant gives that answer word for word, with no model call (`CUSTOM_ANSWER_MIN_SCORE`).

**The email to the people who asked** (`GAP_FOLLOWUP`, checkbox per draft, template `visitor_gap` in Console → Emails):
everyone who asked and left an email on that browser (sign-in, booking, enquiry, hand-over) gets the answer, quoting
their own words, with a "Read more" link, an "Ask Deep more" button and Deep's booking link. Safeguards:

* only questions asked after the loop went live (`settings` key `gaps:since`, written on the first run), so switching it
  on never emails people (or colleagues' test chats) from before, and only within `GAP_FOLLOWUP_MAX_DAYS` (45);
* never addresses on the host's own domain (`HOST_EMAIL`, `EMAIL_FROM`), never anyone who opted out;
* it goes out 10 minutes after approval (time to undo: dismissing the draft cancels it), one email per person with all
  their answered questions, at most one every 3 days (sent every 15 minutes);
* every email has a signed unsubscribe link (`/email/optout`, a page with a button: mail scanners that open links change
  nothing); `email_optouts` is checked before every send.

The email's links carry `utm_campaign=gap-followup`, so session tracking counts who came back and who booked.

Endpoints: `GET /admin/gaps/drafts?status=draft|approved|dismissed`, `POST /admin/gaps/run`,
`POST /admin/gaps/drafts/{id}/approve|dismiss|restore|redraft`, `GET /admin/gaps/drafts/{id}/askers`,
`POST /admin/gaps/followups/send`, `GET|POST /email/optout`.

## 14. Call outcomes and the learning lead score (added 2026-10-14)

After every call Deep says how it went with one tap; the assistant drafts the follow-up email, and the lead score learns
which signals really lead to good calls. `app/outcomes.py`.

**"How did the call with Ada go?"** `OUTCOME_ASK_AFTER_MINUTES` (20) after a booked call ends, Deep gets one email with
the call, the lead score at booking and four buttons: **Good fit · Follow up · Not a fit · No-show** (hourly at :05;
only calls booked after the feature went live, `outcomes:since`; calls that ended more than 3 days ago are not asked
about). The buttons are signed links (`LINK_SECRET`, else derived from `ADMIN_TOKEN`) to a small page with that choice
preselected, a note box and "Save": a mail scanner opening the link changes nothing.

**The follow-up draft**: Good fit, Follow up and No-show draft an email to the visitor right away (one model call, from
the brief, the chat and Deep's note; never invented prices, dates or promises; a no-show gets "sorry we missed you" with
the booking link). The page shows it editable with "Send to Ada"; replies go to Deep. Nothing reaches the visitor
without that press, and it is sent once. Not a fit drafts nothing.

**Console → Bookings**: an "outcome" column ("rate it" for calls that ended without one); open a booking for the four
buttons, the note, and the follow-up editor ("Send", "draft again").

**Learning** (`learn`, nightly at 03:40 and after every outcome): every rule of the lead score now has a key. Good fit
and Follow up count as good calls, Not a fit and No-show as not. With n rated calls and a good-call rate p, each rule's
rate among the calls that had it is smoothed toward p (as if 5 more calls at p) and becomes a correction of
`40 × (rate − p)` points, capped at ±20, and 0 for a rule seen in fewer than 3 calls. The corrections apply to every
score once `SCORE_LEARN_MIN` (20) calls are rated (`SCORE_LEARNING`); before that Console → Bookings shows what they
would be. Each reason in a brief keeps its original points (`base`) next to the learned ones, so the change is visible.
A correction never flips a rule's sign (a bonus bottoms out at 0, a penalty tops out at 0). Learning reads each call's
score at booking (`brief.at_booking`) when it was made by the current rules (`precall.VERSION`), else scores it again;
staff and test bookings (`internal`, `test_traffic`) are left out.
The card also shows how far apart good calls and the rest score, before and after learning.

**Weekly digest**: a "Results" section with the week's calls by outcome and the source that brought the most good
calls, and the knowledge-gap loop (drafts waiting, approved, emailed, came back, booked).

Endpoints: `POST /admin/bookings/{id}/outcome`, `POST /admin/bookings/{id}/followup/draft|send`,
`GET /admin/score/learning`, `POST /admin/score/learn`, `POST /admin/outcomes/ask/run`, `GET|POST /outcome/{id}`,
`POST /outcome/{id}/send`.

## Operations

* Scheduler jobs (`app/main.py` startup): `recrawl`, `tracking_purge`, `weekly_digest`, `nudges`, `reminders`, `hot_leads`,
  `gap_drafts`, `gap_followups`, `outcome_asks`, `score_learning`.
* New tables/columns: `companies`; `leads.company`, `leads.enrichment`, `leads.nudged_at`, `leads.confirmed_at`; `gap_drafts`,
  `gap_asks`, `gap_followups`, `email_optouts`; `bookings.outcome`, `outcome_note`, `outcome_at`, `outcome_asked_at`, `followup`.
* Turn anything off without a redeploy: `DIGEST_ENABLED=false`, `NUDGE_ENABLED=false`, `ENRICH_ENABLED=false`,
  `MULTILINGUAL=false`; suggestions fall back to the fixed defaults when the database is unreachable.
