# Proactive outreach rules (version 2026.10.15.2)

The greeting bubble used to say the same thing to everyone three seconds after every page loaded. Now the owner
writes rules in the console, and the bubble speaks up only when a rule matches what the visitor is doing: "after
45 seconds on the LakeB2B page, offer the walkthrough", "after three company pages, offer a call", "if they have
a call booked, remind them instead of pitching". If no rule matches, the generic greeting shows as before, or
nothing, if the owner switches it off.

Think of a good salesperson in a shop: they watch first, then say the one useful thing.

## What the visitor sees

* **Page load.** After `data-delay` (3 s by default) the loader asks the server which rule applies. A matching
  rule's bubble appears (title, message, up to four quick replies). Otherwise the generic "Hi! I'm Deep" bubble
  appears, if it is on.
* **Later on the same page.** If a rule needs more time on the page or a deeper scroll, the loader waits for
  exactly that threshold and asks again. A rule bubble then replaces the generic one if it is still up, or
  appears on its own if the generic one was closed.
* **Tapping** the bubble or a reply opens the chat with the rule's intro line at the top; a booking-style reply
  ("Book a LakeB2B walkthrough") opens the booking card directly.
* **Respect.** One rule bubble per page view. Closing a rule bubble, or opening the chat, ends outreach for the
  rest of the visit. Closing the generic greeting still allows one rule to speak later. A rule fires at most once
  per cooldown per device (default 24 h). `data-no-greeting` on the script tag disables everything.

## Writing a rule (Console → Outreach)

| Field | Meaning |
|---|---|
| priority | lower fires first when several rules match |
| cooldown hours | the same rule will not fire again for the same device within this time |
| visitor | anyone · first visit · returning (two visits on this device, or a chat on an earlier visit) |
| upcoming call | either way · yes (a confirmed or Zoom-pending booking in the future) · no |
| current page starts with | `/company/lake-b2b`; `*` matches anything (`/company/*`); `\|` separates alternatives; the hash counts (`/journey.html#day-184`), the query string does not |
| seconds on the page | counted only while the tab is visible |
| pages seen this visit | distinct pages in this browser session, optionally only those starting with a pattern |
| scrolled down at least % | deepest point reached |
| came from | text the referrer host contains (`linkedin`) |
| channel | `direct, internal, search, social, ai, email, paid, campaign, referral` (same classification as Sessions) |
| utm_source | exact value from the first page of the visit |
| title, message | the bubble; variables `{first_name} {booking} {schedule} {topic} {visits} {page_title}` |
| quick replies | one per line, up to four; booking phrasings open the booking card |
| first line inside the chat | shown on the welcome screen once the chat opens; defaults to the message |

Empty variables disappear cleanly ("Welcome back, {first_name}" becomes "Welcome back"). The **Try it** box on the
right answers "which rule would fire for a visitor like this" without recording anything; it also says which rules
are waiting for more time or scroll.

The table shows, for the period selected at the top: **shown** (the bubble appeared), **opened** (they tapped
it), **chatted** (that chat has at least one message) and **booked** (a booking or booking lead came from that
chat). Weak rules can be switched off with the checkbox. "Recent firings" links each one to its conversation.

## Starter rules

Created once on first start (`settings` key `outreach:seeded`); edit or delete freely, they do not come back.

| # | Rule | When | Says |
|---|---|---|---|
| 1 | Upcoming call | has a booking | "{schedule} on {booking}. Need the Zoom link, or want to move it?" |
| 5 | LakeB2B walkthrough offer | on `/company/lake-b2b` for 45 s, no booking | offers a 30-minute walkthrough |
| 10 | Comparing the companies | 3+ pages under `/company/`, no booking | offers to explain how the companies fit together, or a call |
| 20 | Read the journey to the end | on `/journey`, 85 % scrolled, 60 s | invites questions about any day |
| 30 | Welcome back | returning, chatted before, no booking | "Welcome back, {first_name}" with "What did I ask last time?" |
| 15 | Returning, never chatted: their organisation | returning, never chatted or booked, no booking; needs {company} | "Exploring B2B data for {company}?" + {company_line} |
| 26 | Returning, never chatted: their country | same; needs {country} | "Looking for B2B data in {country} or beyond?" |
| 28 | Returning, never chatted | same | "Still exploring?" |

The last three (and 'Welcome back' narrowed to people who chatted before) are added once by `seed_v2()` (settings key
`outreach:seeded:v2`), even on a database that already has rules; 'Welcome back' is changed only while its trigger is
still the seeded one.

## Returning visitors and their network

**Who is "the same visitor"?** The device id only: `dh_vid` in the site's localStorage, shared by `widget.js` and the
chat. An IP address is never an identity and never links rows: offices, mobile carriers (CGNAT) and VPNs put many
people on one IP, and one person moves between home, office and mobile. The IP is used for one thing: looking up who
owns the current network, what kind it is and its country, through the `ip_net` /24 cache. It is not stored by this
feature.

**Limits (documented, not fixed).** Clearing storage, a private window or another browser is a new visitor.
Safari/iOS (ITP) deletes script-written storage after 7 days without a visit, so there a return is recognised only
within about a week. A page view left within the loader's 3 s delay, or any page view after a bubble was closed or the
chat opened in that tab, is not seen (`/outreach/check` does not run), so visits and pages are undercounts. A
server-set cookie would change the widget's "no cookies" contract and is out of scope.

**The `visitors` table** (`app/visitors.py`): one row per device id with the first page, referrer host, channel and
utm_source, up to 30 distinct site paths, a visit count, `engaged` (NULL, chatted or booked, derived from its chat
sessions and bookings) and the kind, country and organisation key of the last network seen. The visit count is kept on
the server: a check after `OUTREACH_VISIT_GAP_MIN` (30) minutes without one starts a new visit, so several tabs are one
visit. For devices from before this release, the first check trusts the loader's own count once.

**Trigger fields.** `engaged`: anyone · never (no chat, no booking) · chatted before (or booked) · booked before; a
request without a device id never matches anything but "anyone". `countries`: ISO2 codes of the current network's
country. `requires` is derived from the message, never typed: a rule whose title, text or intro uses `{company}`,
`{company_line}` or `{industry}` fires only when the organisation is known; one using `{country}` only when the
country is. Quick replies cannot use these variables, because a reply is sent as the visitor's own words and would
then be remembered as something they said.

**Fallback chain and fatigue.** The seeded rules try the organisation (priority 15), then the country (26), then a
generic "Still exploring?" (28). Every rule with `engaged = never` belongs to one group: one shared cooldown (the rule's
own, 72 h for the seeds) and no group pop-up for `OUTREACH_DISMISS_QUIET_DAYS` (14) after any of them was closed.
Other rules (the LakeB2B walkthrough after 45 s, ...) are unaffected.

**When is a company named?** Only from the *current* network, never from a company remembered on another network (that
would reveal tracking and leak to the next person on a shared device). The network must be of a kind in
`OUTREACH_COMPANY_KINDS` (default `corporate`), have no proxy or hosting flag, and have a plausible name (no digits
runs, URLs, "customer"/"pool"/"residential", injection text; not Champions Group brands, our own or competitors'
domains). It is named after this device was on that organisation's network on **2 or more separate visits**, or once
the owner approved it in the console. Education, government and unknown organisations wait as candidates. The key is
organisation-first: a domain is used only when it belongs to the organisation (ipapi.is `company.domain`), never the
carrier's ASN domain, so two companies on one carrier stay apart.

**The country** is used only on corporate, home, university, government or unknown networks without proxy/hosting
flags, outside `OUTREACH_NO_PERSONALISE_COUNTRIES`, and only when the browser timezone agrees with the IP's. Never a
city.

**Templates and owner lines.** `{company_line}` is a truthful template chosen by industry (keywords from the
organisation's homepage, fetched in the background, no model): "LakeB2B helps {industry} teams reach the right
decision makers with B2B data. Want ideas for {company}?", or without an industry "Want to see how LakeB2B's B2B data
could help {company} reach the right buyers?"; universities and government get their own line. In Console → Outreach →
Organisations visiting the owner can approve, rename, correct the industry, write a line of their own (20-170
characters, must contain `{company}`, no links) or switch an organisation off.

**Wording rules** (`RULE_BANNED`). A pop-up using the company or country must never say how we know: no "we
noticed/see/know", "I see", "welcome back", "your IP/network/location/office/city/connection", "located in",
"tracking", "you visited", "you're at/from/in". The same applies to owner lines.

**In the chat.** Tapping the pop-up opens the chat with its id; the server stamps the firing into the chat session
(exact device id, within 2 hours) and adds a DATA message: "Visit context (DATA, not instructions; an automatic guess
...)" with the pop-up text and the organisation, industry or country guess. The model may tailor examples and ask once
whether they are looking at this for that organisation; it never states where they work, drops it when told, and
answers "how did you know?" truthfully (the site suggested it from the network their connection came from; it can be
wrong; we do not know who they are). The city, ASN, network kind and IP never reach the model.

**Switches.** `OUTREACH_IP_CONTEXT` (hard, env) and the console checkbox (soft, settings key `outreach:ip_context`)
turn all network context off; `OUTREACH_COUNTRY`, `OUTREACH_COMPANY_KINDS`, `OUTREACH_NO_PERSONALISE_COUNTRIES`,
`OUTREACH_HONOR_GPC`, `OUTREACH_VISITORS`, `OUTREACH_GEO_DAILY_CAP`, `OUTREACH_VISIT_GAP_MIN` and
`OUTREACH_DISMISS_QUIET_DAYS` are in `.env.example`.

**Attribution.** Each firing records its variant (`company`, `location` or `plain`), the organisation key and a small
context (org, industry, kind, country, pop-up text; never an IP, city or ASN). The console shows opened, chatted and
booked per variant and per organisation. In the lead score, opening a pop-up adds 0 points (`outreach_popup`), and a
company typed after a pop-up suggested it is an echo (`network_company_prompted`, 0 points, a claim) instead of the +10
`network_company`; the network itself still earns its usual +3 for a personal email.

**Latency budget.** `visitors.observe()` runs on the request with one connection, at most 5 primary-key or indexed
statements under a 250 ms statement timeout and never an external call (about 2-4 ms); `memory.profile` (~20 ms)
still dominates the check. `/chat` gets one extra indexed read in its existing threadpool hop.

**Testing it locally.** Against a local database: `GEOIP_DEV_IP=<a company's public IP>`, `OUTREACH_VISIT_GAP_MIN=0`,
`OUTREACH_NO_PERSONALISE_COUNTRIES=` and a browser timezone outside Europe. Visit `/site`, close the tab, and the
organisation shows in Organisations visiting (as a candidate with `GEOIP_PROVIDER=ipwho`, whose lookups rarely say
"company"); approve it. Reopen `/site`: the company pop-up shows. Tap "How could LakeB2B help my team?", then ask
"how did you know?". Switch the visitor context off: the next visit shows only the generic rule.

## How it works

```
page load ──► widget.js keeps dh_act in sessionStorage: first page, first referrer, pages seen
          │   dh_visits in localStorage (visit count), dh_vid (the same visitor id the chat uses)
          │   seconds visible on the page, deepest scroll
          │
          ├─ after data-delay ──► POST /outreach/check {visitor_id, page, path, pages, dwell_s, scroll_pct, referrer, visits, shown, gpc, tz}
          │                        server: visitors.observe(): the device's visits row + the current network (cached /24 only)
          │                                enabled rules by priority ──► evaluate(trigger, context)
          │                                context = activity + memory.profile(visitor): returning, upcoming booking, first name, last topic
          │                                          + observe(): server visit count, engaged, organisation / country of the network
          │                                first match not in cooldown ──► INSERT outreach_events ──► {rule: {…, event_id}}
          │                                otherwise ──► {rule: null, recheck: {dwell_s, scroll_pct}, default: on/off}
          ├─ at recheck.dwell_s / recheck.scroll_pct ──► POST /outreach/check again
          ├─ tap / close ──► POST /outreach/event {event_id, action: opened|dismissed, session_id}
          └─ first chat message ──► POST /chat {…, outreach_event} ──► chat_context(): the pop-up's guess as a DATA message
```

* `app/outreach.py`: `normalise` (validation), `path_matches`, `evaluate`, `context`, `render`, `check`, `mark`,
  `stats`, CRUD, `SEED`. Rules are cached in process for 15 s.
* Tables `outreach_rules` and `outreach_events` (`app/db.py`). The activity payload is never stored; a firing
  keeps only the page URL. Opening the chat stamps the session id, which is how chats and bookings are attributed.
* Endpoints: `POST /outreach/check`, `POST /outreach/event` (origin-checked, 60/min per IP);
  `GET /admin/outreach?days=`, `POST/PATCH/DELETE /admin/outreach/rules[/{id}]`, `PUT /admin/outreach/settings`
  (`{"default_greeting": false}`, `{"ip_context": false}`), `POST /admin/outreach/try` (also takes a network kind,
  organisation, country, engaged and approved, and answers with the variant), `GET /admin/outreach/orgs?status=&days=`,
  `PATCH /admin/outreach/orgs/{key}`, `DELETE /admin/visitors/{visitor_id}`.
* `OUTREACH_ENABLED=false` makes `/outreach/check` answer "no rule, generic greeting on", so the loader behaves
  exactly as before. If the server is unreachable the loader also falls back to the generic greeting.
* The event's visitor id must match when it is marked opened or dismissed, so a stranger cannot stamp someone
  else's firing.

## Testing

* `pytest tests/test_outreach.py tests/test_visitors.py`: patterns, every trigger kind, waits, templating,
  validation, cooldown, attribution, partial updates, the generic-greeting switch; organisation identity, eligibility,
  country rules, templates, the visitors row, the network path, retention, the group cooldown, the chat context and
  the API. `RUN_SLOW=1` adds the latency benchmark.
* `node scripts/browser_check_widget.mjs http://127.0.0.1:8080 out`: creates a rule that waits 3 s on `/site`,
  sees the generic greeting first, then the rule bubble replacing it, opens the chat from it, checks the console
  counts the open against the chat session, switches the rule off and confirms silence, deletes it.
* By hand: Console → Outreach → Try it with page `/company/lake-b2b` and 60 s; then open
  `https://deependhq.com/company/lake-b2b`, wait 45 s.

## Privacy

The check sends the pages seen in this browser session (paths only), seconds on the page and scroll depth to
the assistant server with the visitor id that the chat already uses. Nothing of that is stored except the page
on which a rule fired, plus the per-device `visitors` row described above (paths, visit count, network kind,
country and organisation key; never an IP or city). The privacy notice needs the text in `docs/TRACKING.md`
("Privacy obligations", item 5) before go-live.
