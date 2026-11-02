# Features

Everything ask deep does, in detail. The [README](../README.md) has the short version.

## At a glance

| | |
|---|---|
| **Messenger like Intercom's** | The widget looks and works like the Intercom messenger on snitcher.com: **Home** (a dark header with the greeting and Deep's photo, the recent conversation, "Ask a question", "Book a call with Deep", "Search for help" with top articles), **Messages** (past conversations, unread badge, "Ask a question") and **Help** (collections, articles, search), with a bottom tab bar; the chat has Intercom's header ("The team can also help"), grey bot bubbles and a two-row composer. Full screen on phones. |
| **Help center** | Collections of articles in the Help tab (`app/help.py`): starter articles made from deependhq.com (companies, toolkit, the Now page) plus built-in ones on booking and the assistant; Deep writes and edits more in Console → Help center. Search by meaning and words; articles Deep writes also become sources for the bot's answers, and their links open inside the messenger (`#dh-help=<slug>`). |
| **News tab** | Intercom's fourth tab (`app/news.py`), per tenant (LakeB2B first, `NEWS_TENANT`): the WordPress blog RSS and new or changed pages in the typed sitemaps (news, case studies, webinars, guides, white papers…) hourly, the YouTube channel daily, all published by themselves; press mentions from Bing News daily, kept only with the exact word "LakeB2B" and held until a rep approves them in Console → News; and "Publish to the news" for a LinkedIn or X post, a launch or an event, which can be pinned. Newest first, last 30 days, at most 20; a red dot marks news the visitor has not seen, and the newest item is featured on Home. **Dynamic checking** (`NEWS_DYNAMIC`, on by default): each source is checked on its own schedule, again within 15–30 minutes after a site changes and less often while it stays quiet (blog 15 min–2 h, sitemaps 30 min–4 h, YouTube 30 min–6 h, mentions 6–24 h); unchanged feeds cost one 304 or a hash compare; an edited page is refreshed and labelled "Updated"; a page removed from its sitemap or answering 404 is taken off by itself (and comes back if it returns); the open widget refreshes the tab every 2 minutes. Console → News shows each source's last check, last change, next check and errors, and **Find sources** reads a new website (blog RSS, sitemap types, YouTube channel) to fill the tenant form. **Like Snitcher's (Intercom) News**: feeds to filter by (Latest, Blog, Videos, Newsletters, Case studies, Guides & papers, Announcements, In the news), cards with "New", the first label and "+ N labels", "You're all caught up!"; an item opens inside the messenger with all its labels, "Shared by" with the author and age, the article itself (safe HTML from the feed or the page; videos play inline), a link out and "How would you rate this?" 💜😴👎🎉 (one per visitor, counted in the console with views); per-item read state and an unread count on the tab; a new item pops up once above the closed launcher (`NEWS_POPUP`, or `news-popup="off"`); feeds start with the newest few pages of each type. |
| **Company websites in the answers** | `app/sites.py`: besides deependhq.com, the assistant answers from the websites of the News tenants (LakeB2B, SPAN Global Services, …). Every page in their sitemaps (minus theme parts, taxonomies and what robots.txt disallows) is read, cleaned of menus and footers, and indexed next to deependhq.com's pages (`pages.site`); every `KB_SITES_EVERY_HOURS` (6) only new and changed pages are read again and removed ones leave. A question that names a company, or one the index cannot answer, also asks that site's own search live (WordPress `/wp-json/wp/v2/search`), cites the best passages and indexes those pages on the spot. deependhq.com's own pages win a close call unless the company is named. Console → News shows pages and passages per site and can re-read them now. |
| **Answers with sources** | Retrieval over the crawled deependhq.com (llms-full.txt, data.js, sitemap pages), with a confidence floor: off-topic questions get a polite refusal instead of a guess. Prompt-injection fences on everything retrieved. |
| **Booking in the chat** | Call type → date → time → details → confirm. The visitor can add guests and gets a Zoom link and an `.ics` invite. Reschedule, cancel and "book again" also work from the chat, and every email carries a private manage page with a two-step cancel. Uses Zoom's official API, a public-page fallback, or a browser worker on the public scheduler page. |
| **Branded booking emails** | Every booking email (confirmation, new booking, cancelled, moved, reminders, the host's day-before brief, guest notes) comes in one HTML design, "Ledger", with a plain-text part that stays editable in the console. No images: it reads the same with images blocked and in dark mode. |
| **Ask Deep from every email** | Visitor and guest booking emails end with one-tap questions that open the assistant already knowing that booking. The booker's earlier website chats join the memory on whatever device they open it on; guests stay separate. |
| **Pre-call brief and lead score** | Before every call Deep gets a brief: who they are, what they asked, pages they read, where they came from and a 0–100 score with a reason for every point. Hot leads who never booked trigger an alert. |
| **Honest lead score** | Points come only from evidence the visitor cannot simply type: a company email whose domain was checked (website, MX record or DNS), the network matching their company, what they did on the site. What they only typed (company, role, budget) is listed as a claim and scores 0. Staff, test, competitor and throwaway addresses are flagged. Every line says whether it is *checked*, *seen* or a *warning*, and a thin record reads "Not enough data yet" instead of "Cold". |
| **Host booking page** | "View booking details" in Deep's emails opens a private, phone-friendly page: status, lead score, join link, who they are, where they came from, the brief, the whole chat and earlier visits. Signed link bound to the booking, read-only on open (mail scanners click everything), never shows IPs or the visitor's manage links. |
| **Visitor tracking and network lookup** | Every chat session gets a row recording how the visitor arrived (direct, search, social, AI assistant, email, paid, campaign, referral, with UTM tags), the city and country of their IP, and the network behind it: its owner and kind (company, home or mobile broadband, cloud, VPN or relay, coworking, university, government). The brief says whether that network matches the company they typed or their email domain. Works with no API key; a MaxMind key keeps every lookup on the server ([below](#visitor-tracking-and-ip-lookup)). |
| **Returning visitors who never chatted** | The greeting can recognise a returning browser and, on a company network or by country, offer a pop-up such as "Exploring B2B data for Acme?". The IP is never stored for this; the EEA, UK and Switzerland, Global Privacy Control and Do Not Track are excluded by default. A company is named only after 2+ visits from its network or the owner's approval in the console, where any organisation can be switched off. |
| **Working memory** | Within a conversation the bot keeps a structured memory of what the visitor said (needs, region, volume, timeline, tools) and, across visits, a short history, so a long chat or a return visit never starts from zero. Email addresses are never stored in it. |
| **Learns from unanswered questions** | Every night the questions the bot couldn't answer become drafted answers. Deep approves one with a click, the bot answers it from then on, and the people who asked get the answer by email. |
| **Learns from every call** | After each call Deep taps Good fit / Follow up / Not a fit / No-show. The bot drafts the follow-up email, and the lead score re-weights its rules from real outcomes. |
| **Voice in any language** | A mic button and a hands-free voice call. The browser's own speech recognition by default, or server speech-to-text (Whisper, `STT_PROVIDER=openai`) that detects the language automatically, ignores silence and noise and re-reads text written in the wrong alphabet. Answers are spoken back. |
| **Answer cards** | Comparisons, KPI tiles, timelines and next-step buttons rendered under the answer (openui-lang, sandboxed). |
| **Remembers return visitors** | "Welcome back" with the last topic, upcoming bookings, and a conversation history page. |
| **Proactive outreach** | Rules written in the console decide when the greeting speaks up ("45 s on the LakeB2B page → offer a walkthrough"). |
| **Automations** | Weekly digest email, follow-up nudges, reminders the day before, lead enrichment and smart suggestions. All of it runs in the same process. |
| **Owner console** (`/admin`) | Overview, conversations (with each one's memory, and a reply box that answers inside the visitor's chat), bookings with briefs and outcomes, knowledge gaps, sessions, guidance, custom answers, the help center, email templates and outreach (rules and organisations visiting). |
| **Embeds anywhere** | A single dependency-free web component (`<deep-assistant>`) in Shadow DOM. Wrappers for React/Next.js and Vue. Signed-in identity via HMAC token or Clerk JWT. |
| **Safe by default** | CORS allow-list, rate limits, a daily spend cap, an admin token, signed one-tap email links, forwarding headers believed only from trusted proxies, optional IP masking and retention purges for tracking data and memory. |

Each part below says what the feature does, how it works, what Deep and the visitor see, and which settings control
it. The linked guides in `docs/` go further.

## Answers with sources

Every night (`RECRAWL_CRON`, 02:30 IST) the crawler reads deependhq.com (llms-full.txt, data.js and the sitemap
pages), splits it into chunks and embeds them locally. A question is embedded the same way and matched against those
chunks. Before searching, the message is read (`app/rag/understand.py`): small talk ("hello", "how r u", "thanks", "what
can you do?", "is this a bot?") gets a short natural reply the model writes with the conversation in view (never a
word-for-word repeat; varied built-in replies when the model is down), with no search; a greeting in front of a question is dropped; a follow-up
("tell me more", "how is it different from Ampliz?") is rewritten into a standalone question. Questions vectors answer
badly go straight to the page that answers them: who Deep is and where he's based (home page and /now), his tools
(/toolkit), what he's on right now (/now), the full company list (the pillars page plus the exact count of company
pages, so "which companies?" never stops at the top six matches), and the latest entries. A question that names a period
("this week", "last month", "in September", "on October 5", "yesterday") gets the log entries and weekly essays dated in
it, in the visitor's calendar; when there is none yet, the bot says so and gives the newest entry. Every source carries
its date, and a page last updated more than 30 days ago is marked not current, so the June Now page is quoted "as of
June 12", never as today. Between `RETRIEVAL_SOFT_FLOOR` and `RETRIEVAL_MIN_SCORE` the model reads the loosely
related pages and either answers with citations or says it couldn't find it (an uncited answer is logged as a refusal).
If nothing is even that close, the bot politely says it can't answer instead of guessing,
and the question goes to the [knowledge-gap loop](#knowledge-gap-loop). Answers cite their pages. Everything retrieved
is fenced as data, so text on a page cannot give the model instructions. Deep can steer the bot without code changes:
**Guidance** (standing instructions) and **Custom answers** (an exact answer that fires word for word above
`CUSTOM_ANSWER_MIN_SCORE`) are both in the console. Non-English questions are answered in the visitor's language
(`MULTILINGUAL`).

## Booking in the chat, and the visitor's manage page

"Book a call" opens a card in the chat: call type, date, time, details (name, email, company, a note, up to five
guests), confirm. Open times come live from Deep's Zoom Scheduler page (`ZOOM_BOOKING_BASE`). The booking goes through
Zoom's API when Server-to-Server credentials are set together with `ZOOM_ENABLE_API_BOOKING=true` (Scheduler API) or
`ZOOM_HOST_USER_ID` (Meetings API); otherwise a browser worker books on the public page (`BROWSER_BOOKING_ENABLED`),
and when none of these is on or all fail, the time is held and the visitor confirms on Zoom with their details already
filled in. One email address can hold at most `BOOKING_MAX_ACTIVE_PER_EMAIL` upcoming bookings.

Zoom's public pages never show the join link, so for browser bookings the worker adds one mailbox of ours as a guest
on Zoom (`ZOOM_LINK_MAILBOX`, default `SMTP_USER`), and the app reads Zoom's invitation there over IMAP: the join link,
meeting ID and passcode go on the booking, and the confirmation emails (which wait up to `ZOOM_LINK_WAIT_SECONDS` for
it) carry the Join button and the phone row. No Zoom credentials ([BROWSER_BOOKING](BROWSER_BOOKING.md#the-join-link-appbookingzoom_mailpy-2026-10-15)).

The visitor gets a confirmation email with the join link and an `.ics` invite; guests get their own short note.
Moving or cancelling works from the chat ("reschedule my call") and from the email's **View booking details** button,
which opens the visitor's private manage page (`/booking/{id}/manage`, opened with the booking's own private token). Its
cancel takes two steps: **Cancel this booking…** opens "Cancel this booking?" and only **Yes, cancel it** cancels, so a
mail scanner, an old email or a mis-tap cannot cancel a call. Details: [BOOKING](BOOKING.md),
[FAILURE_MODES](FAILURE_MODES.md).

## Booking emails

Every booking-lifecycle email (the visitor's confirmation, Deep's "New booking", cancelled, moved, the day-before
reminders, Deep's day-before brief, the 24 h reminder for an unconfirmed Zoom hold, and the notes to extra guests) is
HTML in one design system, "Ledger" (`app/booking/email_html.py`): a status pill, the heading, an event card with a
live-text date tile, before-and-after times for a move, and bulletproof buttons, built from the real booking: a
"Confirmed" pill and the join link once Zoom has created the meeting, "Awaiting Zoom confirmation" and the prefilled
Zoom link while it is only held. The plain-text part is always sent too and stays the editable template in
**Console → Emails**. The design uses no images, so blocked images change nothing; it has its own dark mode.

`EMAIL_ASSETS_URL` (hosted images, or empty to embed them in each message) is kept for a future email that needs
images; no current email uses one. Every email, who receives it and how to change the wording: [EMAILS](EMAILS.md).

## Ask Deep from a booking email

Emails cannot run a chat (mail apps block scripts), so every email to a visitor or a guest (confirmation, cancelled,
moved, the day-before reminder, the 24 h Zoom reminder, and the four guest notes) ends with a small **Ask Deep** panel:
two to four one-tap questions that fit that email and its state ("How should I prepare for this call?", "How do I
confirm my time on Zoom?", "Book a new time"…) and "Open the assistant". Deep's own emails have no panel.

- **The link** opens the assistant (`/ask`) with a signed token in the URL fragment, so it never reaches a server log.
  The token is tied to one booking, one recipient and that email; it expires `EMAIL_ASK_TTL_DAYS` after the call, and
  rotating the booking's manage token revokes it. The page exchanges it with `POST /ask/claim`.
- **Mail scanners open links**: a plain fetch of `/ask` reads and writes nothing. The tapped question is sent only
  once the page is really open in a browser, once per link and question, and it is stored as sent by the page, not typed.
- **The conversation knows the booking**: call, time in the visitor's timezone, status (confirmed / waiting for Zoom /
  cancelled), guests' first names. It goes to the model as a DATA block, read live every turn.
- **Memory**: on another device (their phone), the booker's earlier website chats join that device's memory, and later
  website visits there carry on. One way only: the phone reads the laptop's history, never the reverse. A browser other
  people used gets the booking context but no history. With `EMAIL_ASK_TARGET=site` the link opens deependhq.com's
  own widget, so on the same browser it is simply the same memory.
- **Booker vs guest**: the booker can reschedule or cancel from that chat; a guest can ask questions but never change
  the booking, and never sees the booker's address, notes or chats.
- **Lead score**: opening a link or tapping a question earns nothing. A message the booker actually types in such a
  chat is `email_ask_chat`, +3, seen.
- **Analytics**: opens, taps and typed chats per email in `/admin/metrics` (`email_ask`); opens may include scanners.

## Pre-call brief and the honest lead score

Before every call Deep gets a one-page brief on the person (`app/precall.py`), built only from what the assistant
already stores; no paid data. It gathers every chat session of that person (the booking's, every session of the same
browser and every session tied to the same email), then lists the questions they typed, the pages they opened the chat
on, how they arrived, where they were and on which network, earlier bookings and cancellations, the company read off
their email domain, their note and guests. One model call (`PRECALL_MODEL`) turns those facts into a short summary,
talking points, questions to ask and watch-outs; when the model is off, slow or unusable, a rule-based brief from the
same facts is used, so a brief always exists.

**The score** starts at 10 and runs from 0 to 100. Hot is 60+, warm 35+, otherwise cold. Every rule has an evidence
class, and every "Why this score" line ends with its tag:

* **checked**: compared against something the visitor cannot simply type (their email domain's website or mail
  server, their network, a verified sign-in, an earlier call Deep rated);
* **seen**: something the system watched them do (questions, visits, pages, call type);
* **their word** (a claim): something they only typed. Company, role, budget, volume, timeline, team size and tools
  are shown under "What they say (not scored)" and earn **0 points**;
* **warning**: a sign that needs a look. These also appear as flags at the top of WATCH OUT.

The main rules (the full table is in [AUTOMATIONS §12](AUTOMATIONS.md)):

| Group | Signal | Evidence | Points |
|---|---|---|---|
| Risk | staff or test address (`SCORE_INTERNAL_DOMAINS`, `SCORE_INTERNAL_EMAILS`, `HOST_EMAIL`) | warning | −50 |
| | test booking ("test booking" in the note, name or company, or 5+ bookings from one address) | warning | −30 |
| | competitor address (`SCORE_COMPETITOR_DOMAINS`) · throwaway inbox (mailinator, yopmail…) | warning | −20 · −20 |
| Fit | company email whose domain was checked (website read, MX record, or the domain resolves) | checked | +15 |
| | university email · personal email | checked · seen | +3 · 0 |
| | company email whose domain does not exist or takes no mail | warning | −15 |
| | typed company · company email not checked yet | their word | 0 |
| | network matches the typed company / the email domain / another company's network (the first and last only without a company email) | checked / checked / seen | +10 / +5 / +3 |
| | signed in with this very email · Deep rated an earlier call Good fit or Follow up | checked | +5 · +10 |
| | guests added: 1 / 2 / 3+ | seen | +4 / +6 / +8 |
| | target country (`SCORE_TARGET_COUNTRIES`, off by default) · earlier calls that took place | seen | +5 · +5 |
| Intent | call type (`SCORE_CALL_TYPES`: demo 10, GTM session 8, discovery 0) | seen | 0–10 |
| | asked about pricing, a trial or sample data, contracts, implementation | seen | +20 for the first topic, +5 each more (max 30) |
| | described the data they need · booking note with 2+ needs / 1 need | seen | +5 · +10 / +5 |
| | call within 3 days / a week · asked for a person · campaign / search or AI · a key page (`SCORE_KEY_PAGES`) | seen | +5 / +2 · +5 · +5 / +3 · +5 |
| Engagement | questions typed: 6+ / 3–5 / 1–2 · visits: 3+ / 2 · 5+ minutes on the site | seen | +15 / +10 / +4 · +15 / +8 · +3 |
| Risk | personal email claiming a well-known brand nothing confirms · placeholder company · no real name | warning | −5 · −5 · −5 |
| | name does not match the personal email address · call more than 3 weeks away · call moved once | warning | −3 · −3 · −3 |
| | cancelled before · missed a call before · Deep rated an earlier call Not a fit | warning | −10 · −10 · −5 |
| | asked about jobs · reads like a vendor pitch | warning | −25 · −15 |
| | a company typed right after our own pop-up suggested it (an echo, not evidence) | their word | 0 |

**The email domain check** (`DOMAIN_CHECK`) is what lets a company email earn its +15: a DNS lookup of the domain's
MX and address records, needed when the homepage fetch did not already prove it. It runs only on worker threads,
never while the visitor waits, through the system resolver and then `DOMAIN_CHECK_FALLBACK_NS` (those resolvers see the
domain, never the address). A good result is kept 30 days, a dead one 3 days. It needs `dnspython` (in
`requirements.txt`); without it every domain reads "not checked" and startup warns. "Checked" never means "verified": a
real company domain proves the company exists, not that this person works there.

**Shared browsers.** When another person's email shows up on the same browser (a colleague's booking, a family
laptop), only this person's own sessions count, so someone else's visits, questions or network never move their score.

**The verdict** is the headline of the brief: Hot, Warm or Cold lead, or **Not a lead (staff or test)**, or **Not
enough data yet** when the score is under 35 with no checked points, no engagement and no hand-over request. The brief
also carries an evidence line such as `Evidence: 15 pts checked · 58 pts seen · 1 claim not scored`, and keeps the
score as it was at booking time; later refreshes never overwrite it.

**Where Deep sees it:** in the "New booking" email (a hot or warm lead is named in the subject), in a "Brief for
tomorrow" email the day before (`PRECALL_HOST_REMINDER`), on the [host booking page](#host-booking-page), and in
**Console → Bookings** with "refresh brief" and "email it to me". **Hot-lead alerts** (`HOT_LEAD_ALERTS`,
`HOT_LEAD_SCORE`): hourly, anyone who left an email, chatted in the last 24 hours, has been quiet 30+ minutes, scores hot
and has no booking gets one alert to Deep, at most once per 14 days per email and 5 per run.

## Call outcomes and the learning score

`OUTCOME_ASK_AFTER_MINUTES` (20) after a booked call ends, Deep gets "How did the call with Ada go?" with four buttons:
**Good fit · Follow up · Not a fit · No-show**. Each button is a signed link to a small page with that choice
preselected and a **Save** button, so a mail scanner opening the link changes nothing. Good fit, Follow up and No-show
draft a follow-up email to the visitor at once; Deep edits it and nothing is sent until he presses **Send**.

Every night at 03:40 the score learns from the rated calls (`SCORE_LEARNING`). Each rule's good-call rate is compared
with the overall rate and becomes a correction of up to ±20 points, ignored for rules seen in fewer than 3 calls. The
corrections apply once `SCORE_LEARN_MIN` (20) calls are rated; before that the console only shows what they would be.
Learning never flips a rule's sign, and a claim can only lose points (down to −5), never gain them. Staff and test
bookings are left out. Details: [AUTOMATIONS §14](AUTOMATIONS.md).

## Host booking page

The **View booking details** button in Deep's emails ("New booking", moved, cancelled, the day-before brief, "How did
the call go?") opens `/host/booking/{id}?t=<token>`, a private page made for a phone. Top to bottom: status (Confirmed,
Awaiting Zoom confirmation, Cancelled, Moved), the lead score; Join Zoom / Email them / Open in console; the time in
Deep's and the visitor's time zone and how soon; WATCH OUT; who they are and how far the company is trusted (from their website, from the email domain, or
only typed); guests and their note; where they came from and the network; the full brief with every score line's tag;
the outcome buttons once the call has ended; the whole chat (first 200 messages); earlier visits and earlier bookings.

How it stays safe:

* **Read-only on open.** Mail scanners open every link, so loading the page builds no brief, calls no model and
  changes nothing.
* **The token is bound to the booking row.** It is an HMAC (signed with `LINK_SECRET`) over the booking id and that
  row's private manage token, so a rebuilt database that reuses an id does not open. There is no expiry, because Deep
  needs the page again after the call. Rotate `LINK_SECRET` to revoke every link at once.
* **What it never shows:** IP addresses, user agents, coordinates, the visitor's manage, `.ics` or cancel links, or
  upload URLs. All visitor text is escaped and never turned into a link. The page has no scripts and is sent with
  `no-store`, `no-referrer`, `noindex` and `DENY` framing headers.

Visitor and guest emails never carry this link. In the console, a booking has **copy host link** and **open host
page**. The buttons only work from a phone if `PUBLIC_BASE_URL` is the public https address (see the
[go-live checklist](CONFIGURATION.md#go-live-checklist)). Details: [AUTOMATIONS §15](AUTOMATIONS.md).

## Visitor tracking and IP lookup

**A session row for every visit.** Every chat session gets one row in `sessions`, written through a single path
(`tracking.ensure_session`) by the `/track` beacon, every chat message, a booking, a hand-over, a reschedule or a
cancel, whichever comes first. If the beacon is lost or blocked, `/chat` and `/booking/confirm` carry the same fields,
and a startup and nightly repair (`backfill_orphans`) gives a row to any session that has messages, bookings or leads
but none. The row records how the visitor arrived: the channel (`direct`, `internal`, `search`, `social`, `ai`,
`email`, `paid`, `campaign`, `referral`), referrer, UTM tags, landing page, browser timezone, language, screen size,
visit number and message and lead counts.

**The IP lookup.** Once per session, on a background thread, the visitor's IP is looked up to get:

* **place**: country, region, city, coordinates and timezone;
* **network**: the AS number and owner (for example "Reliance Jio", "Infosys", "Amazon"), and from that a kind:
  `corporate` (company network), `consumer` (home or mobile broadband), `hosting` (cloud server), `privacy` (VPN,
  iCloud Private Relay, Cloudflare WARP, Zscaler…), `coworking`, `education`, `government`, `unknown` or `local`. The
  classifier (`app/network.py`) works from provider flags, a curated list of known networks and name rules, and says
  `unknown` rather than guess.

The network is then checked against what the visitor told us: does it belong to the company they typed, or to their
business email's domain? That feeds the "Where" and "Network" lines of the brief, the network rules of the lead score
(which never cost points: big-company staff often browse through security proxies), the Sessions tab of the console
and the returning-visitor pop-ups. Network details are for Deep only; they never reach the visitor-facing model
(apart from the pop-up guess described below).

How lookups are kept cheap and polite: results are cached per /24 network (IPv4) or /48 (IPv6) for 30 days, so a
provider sees each network once; a failed lookup is retried after `GEOIP_FAIL_RETRY_MIN` and by a job every 10
minutes; each remote provider gets at most `GEOIP_DAILY_CAP` lookups a day and is paused after a 429 or 5 errors in a
row. Private and local addresses are never looked up. For local testing, `GEOIP_DEV_IP` (honoured only with a
localhost database) looks up a public IP of your choice instead of 127.0.0.1, and the command line tool runs one IP
through the whole chain with no database:

```bash
python -m app.tracking 49.207.200.10 'Acme' a@acme.com   # place, network kind, and whether it matches the company or email
```

**Getting the real IP behind a proxy.** With `TRUST_PROXY=true` the app reads forwarding headers, but only from a peer
in `TRUSTED_PROXIES` (private ranges and loopback by default, which suits nginx or Docker in front). `X-Forwarded-For`
is walked from the right past trusted hops, so a visitor cannot forge their IP by sending the header themselves. If
Cloudflare connects to the app directly, add Cloudflare's published ranges to `TRUSTED_PROXIES`; otherwise every
visitor looks like a Cloudflare server and the log shows `forwarding headers ignored` (at most once an hour, when such a
request arrives).

### Does it need an API key?

**No.** Out of the box `GEOIP_PROVIDER=ipwho` uses the free ipwho.is API with no key. A key only changes which service
answers:

| `GEOIP_PROVIDER` | Key | Where the lookup runs |
|---|---|---|
| `ipwho` (default) | none | ipwho.is receives the visitor's IP; ~10k lookups a month on the free tier |
| `ipinfo` | `GEOIP_TOKEN` | ipinfo.io receives the IP |
| `mmdb` | `MAXMIND_LICENSE_KEY` (+ `MAXMIND_ACCOUNT_ID`) | **on this server**: MaxMind's free GeoLite2 files are downloaded and read locally, so no visitor IP leaves the server and there is no lookup quota |
| `ipapi`, `ipapiis` | none | ip-api.com (plain HTTP, non-commercial only; startup warns) or ipapi.is |
| `none` | | no lookups |

Providers can be chained with a comma: the first that answers wins, so with `mmdb,ipwho` ipwho is asked only for
addresses GeoLite2 cannot place, or while the files are still downloading.

### Using a MaxMind licence key

1. Create a free GeoLite2 account on maxmind.com, then generate a licence key (Account → Manage License Keys). Note the
   account ID shown on the same page.
2. Add to `.env`:
   ```
   GEOIP_PROVIDER=mmdb,ipwho
   MAXMIND_ACCOUNT_ID=<your account id>
   MAXMIND_LICENSE_KEY=<your licence key>
   ```
   The account ID is optional but recommended: with it the download uses HTTP basic auth and the key stays out of the
   URL. Without it the older URL that carries the key is used (it is hidden from every log either way).
3. Download the files once by hand (or simply start the app, which downloads them in the background whenever they are
   missing or more than 6 days old):
   ```bash
   python -m app.geoip_update            # --force downloads again even if the files are recent
   ```
   It prints the folder (`data/geoip`, or `GEOIP_MMDB_DIR`) and `updated (build <date>)` for GeoLite2-City and
   GeoLite2-ASN. Each archive is checked against MaxMind's SHA-256 checksum and swapped in atomically. A wrong key or
   MaxMind's daily download limit is reported in plain words; the key is never printed or logged.
4. Restart the app if it was already running. A weekly job (Wednesday 04:50 host time) keeps the files fresh; MaxMind
   publishes updates on Tuesdays and Fridays and its licence requires files no older than 30 days. On Windows a running
   app keeps the files open, so a later manual `--force` fails with "is another process using it?"; the weekly job
   does the update instead. Under Docker the files live in the `geoip` volume.

What changes with `mmdb` first: place, timezone, AS number and owner are the same as with ipwho, and neither GeoLite2
nor ipwho's free tier gives VPN or hosting flags, so the network kinds come out the same. GeoLite2 has no network
*domain*, which has three effects: matching the network to an email domain compares the owner's name instead
(`infosys.com` still matches "Infosys Limited", `tcs.com` no longer matches "Tata Consultancy Services"); organisations
in the pop-up console are keyed by name instead of domain, so their industry is not filled in automatically (set it in
the console) and an organisation already seen under ipwho gets a second entry; and the optional reverse-DNS check
(`NET_RDNS`) recognises the carrier from the owner's name or initials. If naming organisations by their website matters
more than keeping lookups local, use `ipwho,mmdb` instead. Startup warns if a MaxMind key is set but `mmdb` is not in
`GEOIP_PROVIDER`.

MaxMind's licence requires a credit line where the data is used, for example on the privacy page: "This product
includes GeoLite2 data created by MaxMind, available from https://www.maxmind.com". More in
[TRACKING](TRACKING.md#geo-providers-keys-privacy-limits).

## Returning visitors who never chatted

Most visitors never open the chat. The launcher (`widget.js`) keeps a random device id in the site's localStorage
(`dh_vid`, no cookie), and a few seconds after each page load it asks the server (`/outreach/check`) whether a greeting
rule should speak up. That check now also keeps one `visitors` row per device: first page, referrer, channel, up to 30
site paths, a visit count (a new visit after `OUTREACH_VISIT_GAP_MIN` minutes without a check), whether the device ever
chatted or booked, and the kind, country and organisation of its current network. **No IP, city or AS number is
stored for this**, and the IP never links two devices: offices, mobile carriers and VPNs put many people on one IP.

**What the visitor sees.** A returning visitor who never chatted may get one of three seeded pop-ups, tried in order:

1. their organisation: "Exploring B2B data for Acme?" with a one-line pitch matched to the organisation's industry;
2. their country: "Looking for B2B data in Germany or beyond?";
3. a plain "Still exploring?".

Tapping it opens the chat, and only then does the model get the guess, as a DATA message labelled as an automatic
guess. It may tailor its examples and ask once whether they are looking for that organisation; it never states where
they work, drops the guess when told, and answers "how did you know?" truthfully. The city, network kind, AS number
and IP never reach the model.

**When is a company named?** Only from the network the visitor is on right now, never from one remembered from another
network. The network must be a company network (`OUTREACH_COMPANY_KINDS`, default `corporate`) without proxy or hosting
flags, with a plausible name (not our own brands or competitors), and the device must have been on it on **2 or more
separate visits**, or Deep must have approved it in **Console → Outreach → Organisations visiting**. University,
government and unknown networks always wait there as candidates. In that list Deep can approve, rename, correct the
industry, write his own line (it must contain `{company}`) or switch an organisation off.

**Country rules.** The country is used only on company, home, university, government or unknown networks without
proxy or hosting flags, only when the browser's timezone agrees with the IP's country, never for countries in
`OUTREACH_NO_PERSONALISE_COUNTRIES` (default: the EEA, the UK and Switzerland), and never a city. While that list is
not empty, a browser whose timezone starts with `Europe/` gets no visitors row and no lookup at all.

**Respect and wording.** All "never chatted" pop-ups share one cooldown and, once any of them is closed, the group
stays quiet for `OUTREACH_DISMISS_QUIET_DAYS` (14). Browsers sending Global Privacy Control or Do Not Track get no
visitors row, no lookup and no company or country context (`OUTREACH_HONOR_GPC`), and neither do bots; ordinary greeting
rules still apply to them. A pop-up that uses the company or country may never say how we know
("we noticed", "your IP", "located in", "welcome back"…); the console refuses such rules and such owner lines. In the lead score, opening a pop-up adds 0 points, and a
company typed after a pop-up suggested it counts as an echo (a claim, 0 points) instead of the +10 network match.

**Switches:** `OUTREACH_IP_CONTEXT=false` (or the console checkbox) turns all network context off;
`OUTREACH_VISITORS=false` stops the visitors rows; `OUTREACH_GEO_DAILY_CAP` limits page-view lookups.
Details: [OUTREACH](OUTREACH.md#returning-visitors-and-their-network).

## Proactive outreach rules

The greeting bubble speaks up only when a rule written in **Console → Outreach** matches what the visitor is doing:
the page they are on, seconds on it, pages seen, scroll depth, where they came from, channel, `utm_source`, whether they
are returning, whether they chatted before, and whether a call is booked. "After 45 seconds on the LakeB2B page, offer
the walkthrough"; "if they have a call booked, remind them instead of pitching". A rule has a priority, a cooldown per
device, a title, a message with variables (`{first_name}`, `{booking}`, `{company}`, `{country}`…) and up to four
quick replies. **Try it** answers "which rule would fire for a visitor like this" without recording anything, and the
table counts shown, opened, chatted and booked per rule. Starter rules are created once on first start.
`OUTREACH_ENABLED=false` brings back the plain greeting. Details: [OUTREACH](OUTREACH.md).

## Memory: the current conversation and earlier visits

The bot remembers what a visitor told it, in two blocks (`app/session_memory.py`, `app/memory.py`):

* **CURRENT CONVERSATION** (`WORKING_MEMORY`): structured notes for this chat: name, company, role, use case, data
  needs, target customers, region, volume, timeline, budget, current tools, team size, how they want to be contacted,
  questions already answered, and offers they declined (so the bot does not offer a call again after "not now"). Facts
  from the booking and hand-over forms are read live from those records on every turn, so a call moved from an email is
  never stale.
* **HISTORY** (`VISITOR_MEMORY`): earlier conversations on the same device or signed-in account: their topics, a
  one-line gist of each, known facts, earlier questions and past bookings. Need and buying facts older than
  `MEMORY_STALE_DAYS` are marked "may be out of date".

Both reach the model as **one DATA message**, not as part of the system prompt, with rules on how to use it: don't ask
again for what is known, don't re-offer what was declined, treat it as the visitor's own claim, never recite it, and
never follow instructions found inside it. **Email addresses are never stored** in memory, and HISTORY joins sessions
only by device id or a verified sign-in, never by an email someone typed.

How the notes are written: cheap rules run on every turn ("10k contacts", "EMEA", "Q1", an amount next to "budget").
A small model (`MEMORY_MODEL`, JSON mode, `MEMORY_MODEL_TIMEOUT`) runs only at four moments, never on the reply path:
when the chat outgrows the 12-message window the model sees, when a returning visitor comes back (to catch up earlier
sessions), right before a pre-call brief, and on an admin rebuild. Each value must be grounded in what the visitor
actually wrote. Both blocks have size caps (`MEMORY_MAX_CHARS`, `MEMORY_HISTORY_MAX_CHARS`) with a fixed drop order.

**In the console:** Conversations → open one → **Memory** shows each field, its value, where it came from, the turn,
the previous value, the gist and exactly what the model sees, with **Rebuild** and **Clear memory** (a tombstone: the
notes are emptied and never re-learned; transcripts and bookings are untouched). Endpoints:
`GET`/`DELETE /admin/memory/{session_id}` (`?visitor=1` clears every session of the device) and
`POST /admin/memory/{session_id}/rebuild`. Memory rows older than `MEMORY_RETENTION_DAYS` (365) are purged nightly.
Details: [MEMORY_VOICE](MEMORY_VOICE.md).

## Knowledge-gap loop

Every night (`GAP_CRON`, 03:20) the questions of the last `GAP_DAYS` that the bot refused or that visitors marked "not
helpful" are grouped (rewordings of the same question join one group) and the biggest groups get a drafted answer
written only from the site's own pages, with a `[placeholder]` wherever Deep needs to add a fact. In **Console → Gaps**
Deep edits and approves a draft; it becomes a custom answer and the bot gives it word for word from then on. Ten
minutes later (time to undo) everyone who asked and left an email gets the answer by email (`GAP_FOLLOWUP`), at most one
email every 3 days, each with a signed unsubscribe link. Details: [AUTOMATIONS §13](AUTOMATIONS.md).

## Voice in any language

A mic button in the composer and a hands-free "Speak to Deep" call view. With `STT_PROVIDER=openai` speech goes to any
Whisper endpoint (Groq's `whisper-large-v3` by default), which detects the language itself. Recording stops when the
visitor stops talking; silence, coughs and room noise are dropped instead of turning into words; text that comes back
in the wrong alphabet is read again (`STT_HINT_RECHECK`). Answers are spoken back with the browser's voices or
`TTS_PROVIDER=openai`. Measured accuracy and limits: [MEMORY_VOICE](MEMORY_VOICE.md) ("Accuracy").

## Other automations

* **Weekly digest** (`DIGEST_CRON`, Monday 09:00): conversations, questions, resolution rate, bookings, the most asked
  and unanswered questions, leads and call outcomes, as text plus an optional model-designed HTML version
  (`DIGEST_RICH_EMAIL`).
* **Lead enrichment** (`ENRICH_ENABLED`): the company behind a business email, read from its homepage and cached 30
  days.
* **Follow-up nudge** (`NUDGE_ENABLED`): one email to a visitor whose Zoom hand-off is still unconfirmed after
  `NUDGE_AFTER_HOURS`.
* **Day-before reminder** (`REMINDER_ENABLED`): one email before every upcoming booking.
* **Smart suggestions**: the questions visitors really ask most become the quick replies (`SUGGESTIONS_DAYS`).
* **Health checks and alerts** (`HEALTH_CRON`, every 10 minutes, `app/health.py`): the model key is accepted and has
  credit left (`CREDIT_ALERT_USD`), the backup model's key works, answers are not failing at the model, the database is
  reachable, no email gave up, the booking robot is not falling back to the hand-off link. A check that turns warn or
  fail emails `ALERT_EMAIL` (default `HOST_EMAIL`), again every 6 hours while it stays broken, and once when it
  recovers. `GET /admin/health` shows the report (`?run=true` checks now); `/healthz` carries the overall status.
* **Backup model** (`CHAT_FALLBACK_MODEL`, `_API_KEY`, `_BASE_URL`): when the main model fails before the visitor saw
  any text (dead key, outage, `CHAT_TIMEOUT` of 30 s), the same answer is written by the backup, ideally on another
  provider (Groq's `openai/gpt-oss-120b` with the speech-to-text key works). The visitor never sees the switch; the
  inbox records which model answered.
* **Email Deep** (`app/escalate.py`): when an answer is refused or rated down, or the visitor asks for a person, an
  **Email Deep** button opens the hand-over form already filled with an email the assistant wrote from the chat (editable),
  (the summary goes to Deep only); Deep gets the need, the open questions, the visitor's message and the chat, and
  replies straight to the visitor. An email written but not sent is kept and the visitor is reminded (a strip above the
  composer, a note above the closed launcher, again on their next visit). See docs/EMAILS.md.
* **Knowledge switches** (`app/knowledge.py`, Console → Knowledge): one switch per website the chatbot answers from
  (deependhq.com and each company site). A website switched off is not searched, not live-searched and not cited, and
  the model is told it is not covered, so it offers Email Deep or a call instead of guessing. "Try a question" shows
  which pages the chatbot would read. Help articles and custom answers stay on. The company switch is the News
  tenant's *the assistant answers from this website* box, which now really stops its pages from being used.
* **The team answers inside the chat** (`app/team.py`, like Intercom Fin's "The team can also help"): the hand-over
  form puts the conversation in *waiting*; Deep replies from Console → Conversations ("Reply in the visitor's chat"),
  the reply shows in the visitor's chat with his name (the widget checks for replies every 12 s while the team is
  involved) and as unread in Messages; a reply still unread after `TEAM_EMAIL_AFTER_MINUTES` (3) is emailed to them
  once (template *visitor team reply*, with a `#dh-chat=` link that reopens the chat); when the visitor writes again,
  Deep gets one email per `TEAM_HOST_NOTIFY_MINUTES` (15). The assistant keeps answering as before. Mark closed /
  waiting in the console.
* **Conversation rating**: after two plain answers and a minute of quiet, the chat asks once "How was this
  conversation?" (1–5); 3 or less invites a note. Console → Overview shows the average and the share of 4–5.
* **"I don't know" reaches the gap list**: an uncited answer that says the site does not have it is logged as
  unanswered (`not_in_sources`) with the "ask the team / book" offer, even when the retrieved pages scored well.
* **Database backups** (`BACKUP_CRON`, 03:50 nightly, `app/backup.py`): a `pg_dump` of the whole database into
  `BACKUP_DIR` on the host (here `D:\Backups\deependhq-db`), outside Docker, the newest `BACKUP_KEEP` (14) kept; one is
  taken at start-up when the newest is over a day old, and the health check alerts when it is over 36 hours. Added
  after a Docker Desktop reset on 2026-10-28 wiped the database volume. `python -m app.backup list | now | restore <file>`
  (restore replaces the database contents; tested into a throwaway database).
* **Saved email queue** (`MAIL_OUTBOX`, `app/mailer.py`): every email is written to the `outbox` table before it is
  sent and marked sent or failed afterwards; every 5 minutes emails a restart or crash left unsent are sent again
  (after 10 minutes, at most 3 times), and the health check warns when one waits over 30 minutes.
* **One runner for scheduled jobs** (`SCHEDULER_LOCK`, `app/leader.py`): with several workers or servers only the
  process holding a Postgres advisory lock runs the reminders, nudges, digests, backups and the rest; the others wait
  and take over within a minute if it stops. Verified with two copies on one database.
* **Answer-quality check** (`python scripts/eval_answers.py`): 38 real questions in `tests/eval/questions.json`
  (greetings, who Deep is, all 12 companies, dated questions, follow-ups, refusals, injection, booking, Spanish,
  Hindi) asked through the real index and model and graded; exit code 1 on any failure, so run it after a recrawl or a
  prompt change. A few cents per run.
* **Docker database start**: `run.cmd` starts Docker Desktop and `docker compose up -d db` when `.env` names the
  compose database and it is not running, instead of switching to an empty embedded database.

Details: [AUTOMATIONS](AUTOMATIONS.md).

## Privacy: what is stored, and for how long

| Data | Where | Kept |
|---|---|---|
| Chat messages, bookings, leads | `messages`, `bookings`, `leads` | not purged automatically; Deep's team handles deletion requests |
| Session origin: channel, referrer, UTM, landing page, timezone, language, screen | `sessions` | kept as an aggregate |
| Visitor IP and user agent | `sessions` | nulled after `TRACK_RETENTION_DAYS` (90); with `TRACK_IP_MODE=masked` only the /24 or /48 is ever stored |
| City, region, coordinates | `sessions` | nulled with the IP, except on company, university, government and cloud networks |
| Network lookup cache (no IPs, no hostnames) | `ip_net` | 30 days |
| Page views without a chat (no IP, city or AS number) | `visitors`, `org_networks` | `visitors` rows and organisations Deep never reviewed are deleted once idle longer than `TRACK_RETENTION_DAYS` |
| Conversation memory (never email addresses) | `session_memory` | `MEMORY_RETENTION_DAYS` (365) |

The purges run nightly (03:10 tracking, 03:25 memory) and `POST /admin/tracking/purge` runs the tracking one on
demand. `TRACKING_ENABLED=false` turns the beacon into a no-op: sessions then hold only the visitor id and counters,
never an IP, user agent, page or referrer. Global Privacy Control and Do Not Track switch off page-view tracking and the
company and country pop-ups. `DELETE /admin/visitors/{visitor_id}` forgets a device's page views.

The site's privacy notice must describe this before go-live (suggested wording in
[TRACKING "Privacy obligations"](TRACKING.md#privacy-obligations-this-creates)): the chat stores messages, the IP
address and approximate location, and the page the visitor came from; page views on deependhq.com are noted per browser
with the organisation and country of the connection; every remote lookup provider in `GEOIP_PROVIDER` is named, with the
retention period; and, with MaxMind, the GeoLite2 credit line.
