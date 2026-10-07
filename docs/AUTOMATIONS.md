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

## Operations

* Scheduler jobs (`app/main.py` startup): `recrawl`, `tracking_purge`, `weekly_digest`, `nudges`.
* New tables/columns: `companies`; `leads.company`, `leads.enrichment`, `leads.nudged_at`, `leads.confirmed_at`.
* Turn anything off without a redeploy: `DIGEST_ENABLED=false`, `NUDGE_ENABLED=false`, `ENRICH_ENABLED=false`,
  `MULTILINGUAL=false`; suggestions fall back to the fixed defaults when the database is unreachable.
