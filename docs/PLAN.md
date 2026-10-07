# deependhq.com assistant: findings, verdict, architecture, plan

Date: 2026-10-05. Everything in "Findings" was checked live today; nothing is assumed.

## 1. What is on deependhq.com

**What it is.** A build-in-public log for Sreedeep Surapaneni ("Deep"), Group CMO at Champions Group and CEO of
Champions Accelerator. One journey entry per weekday (116 entries since 2026-05-04), 16 weekly essays, pages for the
12 companies, four pillars, a tool stack, a "now" page, a privacy page. The site rebuilds itself nightly from an
Obsidian vault (observed build stamp 19:53 UTC = 01:23 IST).

**Pages (sitemap.xml: 36 URLs).** `/`, `/journey`, `/writing`, `/pillars`, `/toolkit`, `/now`, `/command`,
`/field-notes`, `/privacy`, 12 × `/company/<slug>`, 18 × `/post/<slug>` (weekly essays).

**Content volume.** About 35k tokens in total after cleaning: 22.4k words in `llms-full.txt` (all entries + essays),
~600 words each for pillars and toolkit, ~165 for now, ~1.3k for privacy, 12 short company cards. Dry run of the
crawler today: 149 documents → 196 chunks (median 154 tokens) → embedding cost **$0.0007**. This is a tiny corpus.

**Rendering.** No-build React 18 via babel-standalone, hosted on Cloudflare Pages, but the text is **pre-rendered into
the HTML** (homepage 4.4k visible words with JS disabled, company pages ~500-800, essays ~1.2k). `requests` +
BeautifulSoup is enough. **Playwright is not needed** and is not used.

**Better than crawling: the site publishes machine-readable exports for exactly this purpose.**
* `llms.txt` (index), `llms-full.txt` (every entry and essay as markdown, each with its canonical `Link:`),
* `data.js` (`window.DH_DATA`, the whole site as one JSON object: companies, pillars, toolkit, now, journey, posts),
* `feed.xml`, `sitemap.xml`, and `agents.txt` with house rules for assistants.
The crawler uses these first and falls back to HTML only for pages they don't cover (today: `/` and `/privacy`).

**robots.txt.** `Allow: /` for everyone except named bulk-training bots (GPTBot, ClaudeBot, CCBot, Bytespider,
Amazonbot, Google-Extended, Applebot-Extended, meta-externalagent). Comment: "Assistants and agents that answer questions
about this site are welcome." Enforcement is via Cloudflare AI Crawl Control, so our crawler sends a descriptive
User-Agent (`deependhq-assistant/0.1 (+https://deependhq.com; …)`) and should be allow-listed in Cloudflare if it is
ever challenged.

**House rules from agents.txt that the bot must obey** (baked into the system prompt):
1. quote the day and the date ("day 338, 2026-10-04"); 2. people and clients are anonymised on purpose, keep them so;
3. check freshness (the site flags a stale log); 4. answering questions: welcome, bulk training: no.

**Already on the page.** Every page loads `widgo-gate.js` (which loads the Widgo chat) and the footer says "the Ask
Deep chat is run by Widgo and uses cookies". **Decision: our widget replaces Widgo.** Exact steps for the site repo are
in `docs/WIDGET_SWAP.md`. `ask.js` is the site's own feedback strip, unrelated, and stays.

**Booking link on the site.** `https://scheduler.zoom.us/sreedeep`, which exposes three public schedules:

| slug | title | length |
|---|---|---|
| `discovery-call` | LakeB2B Discovery Call | 15 min |
| `lakeb2b-product-walkthrough-use-case-demo` | LakeB2B Product Walkthrough & Use Case Demo | 30 min |
| `gtm-strategy-session-data-ai-revenue-acceleration` | GTM Strategy Session: Data, AI & Revenue Acceleration | 45 min |

Availability rules observed: Mon-Fri 09:00-17:00 in the host's zone, 30-min increments, 1-day minimum notice, one
optional custom question ("Please share anything that will help prepare for our meeting."). **All three are offered
by the bot**, fetched live from Zoom (so renaming or adding one needs no code change); the bot asks which one fits and
suggests the discovery call for first contact.

## 2. Is the preferred stack the right strategy?

**Yes, keep it, with three adjustments.**

| Item | Verdict | Why |
|---|---|---|
| Python + FastAPI | keep | SSE streaming, tool loop and background scheduler are all simple here. |
| Postgres + pgvector, URL/section per chunk | keep | 196 chunks is small, but Postgres also holds the leads, refusal/handoff log and spend ledger, so one database does everything. HNSW index is created anyway. |
| OpenAI embeddings | **replaced** by a local Hugging Face model (`BAAI/bge-small-en-v1.5` via fastembed, CPU, no key) | Decided 2026-10-05 to remove the paid dependency. 384-dim vectors; the whole corpus embeds in seconds; the nightly re-crawl costs nothing. |
| requests/BS4 vs Playwright | **drop Playwright** | Content is pre-rendered and the site ships `llms-full.txt` + `data.js`. Crawler = fetch three files + two HTML pages. |
| Re-crawl schedule | keep, time it | Site rebuilds ~01:00-01:30 IST; re-crawl at 02:30 IST (`RECRAWL_CRON`). Content hashing makes it a no-op when nothing changed. |
| Streaming UI then widget | keep | `static/chat.html` is served at `/` and `/widget`; `static/widget.js` injects a button + iframe on deependhq.com. |
| Docker → App Runner/ECS or Cloud Run | keep | One image. Cloud Run `asia-south1` with `min-instances 1` is the cheapest option that keeps the in-process scheduler alive. |
| Chat model | **add**: any OpenAI-compatible endpoint; OpenRouter (`openai/gpt-4.1-mini`) for testing and the demo | Decided 2026-10-05. Set `LLM_BASE_URL` + `LLM_API_KEY` + `CHAT_MODEL`; OpenAI `gpt-4.1-mini` remains a one-line switch for production if Groq's free limits bite. |
| Rate limiting | **adjust**: in-memory per IP | Correct for one instance; move to Redis only if you scale past one container. |

## 3. Zoom: what the docs actually say (corrections to the brief)

Verified today against Zoom's API reference, developer forum changelog and the live scheduler.

1. **"Zoom Scheduler has no create-booking endpoint" is no longer true.** `POST /v2/scheduler/attendee`
   ("Create booking for schedule slot") exists with `schedule_id`, `start_date_time` (ISO 8601) and a `booker` object
   (`first_name`, `last_name`, `email`, `time_format`, `phone_number`). It returns the full booking event. The Zoom
   staff answer "that does not exist" dates from Aug 2024 and is outdated.
2. **`GET /v2/scheduler/schedules/{scheduleId}/available_times`** was added on **2026-07-13** and returns day-level and
   spot-level availability. This is the official source for live slots, as the brief prefers.
3. **`single_use_link`** (`POST /scheduler/schedules/single_use_link`) exists, but it is unnecessary for the hand-off:
   the public booking link accepts documented prefill parameters `firstname`, `lastname`, `email`, `month=YYYY-MM`,
   custom-question names and `utm_*`. There is **no documented parameter to preselect a specific time**, so the
   hand-off shows the chosen slot next to the link and the host brief already carries it.
4. **Licensing risk (real, open).** Scheduler is included in Zoom Workplace Business and above or sold as an add-on.
   A forum thread from 2026-08-25 reports `401 Invalid license type` on Scheduler endpoints from a Server-to-Server
   OAuth app despite an active licence and correct scopes, with no Zoom answer yet. Plan for it: the official client is
   primary, and a second client is wired in as fallback.
5. **Fallback: the endpoint the booking page itself uses**, unauthenticated:
   `GET https://scheduler.zoom.us/zscheduler/v1/appointments/{slug}/availableTimes?user=sreedeep&timeZone=<IANA>&timeMin=<ISO>&timeMax=<ISO>`
   plus `GET …/appointments?user=sreedeep` to list schedules. **Tested live today**: returned real spots with
   `status: available|unavailable` for the next two weeks, correctly shifted between Asia/Kolkata and America/New_York.
   **How brittle:** undocumented (though Zoom staff pointed a developer to it in Jan 2025 and it has survived since),
   can change shape or start requiring auth without notice, and is rate-limited by Cloudflare like any page. The code
   detects a shape change (`AvailabilityError: schema changed`) and degrades to the plain booking link; it never
   scrapes HTML, which would be far worse.
6. **Not verified headlessly:** the exact query-parameter names of the official `available_times` endpoint (the
   reference page is a JS app). They are env-configurable (`ZOOM_AVAIL_PARAM_FROM/TO/TZ`), and the response normaliser
   accepts both camelCase and snake_case. Confirm in 5 minutes with your S2S credentials: see `docs/TEST_LOG.md`.

**Resulting booking design.** Show 3 live slots as buttons in the visitor's zone → collect name, email, reason →
`book_slot` re-checks availability → save lead + email host brief → **if `ZOOM_ENABLE_API_BOOKING=true` book via
`POST /scheduler/attendee` and say "Booked"; otherwise hand off to the prefilled Zoom link**. The brief's hand-off
model is kept as the default because it works regardless of the licence question; the API booking is a switch, not a
rewrite.

## 4. Architecture

```
deependhq.com (Cloudflare Pages)
  └─ <script src=assistant/static/widget.js>  ─┐ iframe /widget
                                               ▼
                 FastAPI (one container, Cloud Run / App Runner)
  /chat (SSE) ── origin allow-list ── rate limit ── spend cap
      │
      ├─ injection pre-filter ─────────────► refuse + log
      ├─ retrieve (pgvector, cosine) ──────► score < floor & no booking intent ► refuse + log
      └─ OpenAI chat (stream, tools) ──────► tokens ► browser
             │ get_available_slots(days_ahead) ─► ZoomOfficialClient ─fail─► ZoomPublicClient ─fail─► link
             │ book_slot(start,name,email,reason) ─► re-check ► leads table ► host brief (SMTP) ► API book | hand-off URL
  /admin/recrawl + APScheduler 02:30 IST ─► llms-full.txt + data.js + sitemap HTML ► chunk ► embed ► upsert (hash-skip)

  Postgres + pgvector: pages, chunks(url, section, text, embedding, metadata), events(refusal|handoff|injection|…),
                       usage_daily (spend cap), leads
```

Timezone flow: browser `Intl` → request body → tool execution context. The model never chooses the zone, and `start`
must carry an offset or the call is rejected.

## 5. Build plan against the timeline

**Week 1 (done in this repo, needs keys to run end-to-end): SIMPLE version.**
1. `python -m app.ingest.pipeline` with an OpenAI key and the compose Postgres: crawl, chunk, embed, upsert.
2. `/chat` with retrieval floor, citations, refusal paths, injection fences, rate limit, spend cap, origin allow-list.
3. `static/chat.html` streaming page. Demo material for 9 Oct: run it locally against the live KB; the widget is
   optional for the demo.
4. Tune `RETRIEVAL_MIN_SCORE` with your question list (default 0.35 is a conservative placeholder). Add a
   one-document "all companies" card if "which companies…" questions score low.

**Week 2: live slots in chat (code done, needs Zoom credentials).**
1. Create a Server-to-Server OAuth app with scopes `scheduler:read:admin` (+ `scheduler:write:admin` for API booking),
   set `ZOOM_ACCOUNT_ID/CLIENT_ID/CLIENT_SECRET`, confirm `available_times` works on the account; if it returns the
   licence 401, keep the public fallback as the live path and open a Zoom ticket.
2. Verify the `available_times` query-parameter names and fix the three env vars if they differ.
3. Deploy; embed the widget on deependhq.com; decide what happens to the Widgo script.

**Week 3: hand-off, five tests, failure note, deployment (tests and note done; hand-off coded).**
1. Set SMTP for the host brief (or swap `send_host_brief` for Resend/SES; it is one function).
2. Optionally flip `ZOOM_ENABLE_API_BOOKING=true` after one real test booking through `POST /scheduler/attendee`.
3. Production: Cloud SQL/Neon Postgres, `ADMIN_TOKEN`, Cloudflare allow-list for the crawler UA, uptime check on
   `/healthz`.

## 6. SIMPLE vs AMBITIOUS

| | SIMPLE | AMBITIOUS |
|---|---|---|
| Answers | cited Q&A from the KB, refuses below the floor | same |
| Booking | static link to `scheduler.zoom.us/sreedeep` in the refusal text | 3 live slots as buttons in the visitor's zone, lead capture, host brief email, re-check, hand-off or API booking |
| External deps | OpenAI, Postgres | + Zoom S2S app (optional, fallback exists), SMTP |
| Failure surface | model/DB only | + scheduler down, slot taken, timezone, email |
| Cost per 1k chats | ≈ $0.50-1.00 (gpt-4.1-mini, ~1.5k prompt tokens) | ≈ same + a few tool rounds on booking chats |
| Code path | `respond()` with `tools=None` | `respond()` with `tools=TOOLS` when booking intent is detected |
| Demo on 9 Oct | yes | yes with the public fallback, even before Zoom credentials exist |

Both versions are the same binary: the booking tools are attached only when the message shows booking intent, and the
SIMPLE behaviour is what every non-booking message gets. To demo SIMPLE alone, set no Zoom env and the bot falls back to
the public endpoint; to disable booking entirely, remove `TOOLS` in `app/chat.py` (one line).

## 7. Is booking the right first action?

**Mostly yes, with one change: make "leave a message for Deep" an equal first-class action, and don't push booking.**

* The three Zoom schedules are LakeB2B sales calls. The site's audience is largely readers of a build-in-public
  log (founders, operators, engineers), and for them a 15-minute discovery call is a high-commitment ask that most will
  decline. The highest-value action for that audience is a captured question with an email ("ask Deep, he replies in
  plain text"), which costs the visitor nothing and gives the host a lead anyway.
* For the minority with buying intent (they ask about LakeB2B, Ampliz, data, demos), live slots are exactly right, and
  the agents.txt contact line ("30 minutes, no deck") shows the host wants those calls.

So: the bot answers first, offers booking only when intent appears, and whenever booking fails or the visitor
hesitates it offers the enquiry path, which reuses the same lead table and host brief. That is already how the code
behaves; the only product decision left is copy and whether to show a "message Deep" button in the widget header.

## 8. Defaults assumed until your question list and refusal policy arrive (all marked in code)

* Retrieval floor 0.60 cosine on `BAAI/bge-small-en-v1.5` (calibrated on real scores, see TEST_LOG.md); top-k 6;
  ≤ 9k chars of context; chunks embedded with their page title in front.
* Refuse: anything not answerable from the site; attempts to de-anonymise people/clients; general coding/news/politics;
  requests to change the rules.
* Journey entries are cited by day and date per agents.txt.
* Rate limit 20/min and 200/day per IP; spend cap $5/day; messages ≤ 1500 chars; history ≤ 12 turns.
* Origins: `https://deependhq.com`, `https://www.deependhq.com`.
* Host timezone Asia/Kolkata; preferred visitor hours 08:00-20:00 local when ranking slots.

## 9. What I need from you

1. OpenAI key (to embed and answer), and which chat model you want if not `gpt-4.1-mini`.
2. Zoom: S2S OAuth app credentials from a Zoom admin, then run `python scripts/verify_zoom.py` (steps in
   `docs/ZOOM_SETUP.md`). Until then the bot runs on the public fallback, which works today.
3. ~~Which schedule~~ Decided: all three call types are offered.
4. SMTP or a transactional email provider for the host brief; the host address (default `deep@championsmail.com`).
5. The question list and refusal policy, to tune the floor and the prompt.
6. Hosting choice (Cloud Run vs App Runner) and the subdomain for the assistant (`assistant.deependhq.com` suggested).
7. ~~Widgo~~ Decided: replaced by our widget. Needs a commit to the site repo per `docs/WIDGET_SWAP.md`.
