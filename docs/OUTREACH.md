# Proactive outreach rules (version 2026.10.11.1)

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
| 30 | Welcome back | returning, no booking | "Welcome back, {first_name}" with "What did I ask last time?" |

## How it works

```
page load ──► widget.js keeps dh_act in sessionStorage: first page, first referrer, pages seen
          │   dh_visits in localStorage (visit count), dh_vid (the same visitor id the chat uses)
          │   seconds visible on the page, deepest scroll
          │
          ├─ after data-delay ──► POST /outreach/check {visitor_id, page, path, pages, dwell_s, scroll_pct, referrer, visits, shown}
          │                        server: enabled rules by priority ──► evaluate(trigger, context)
          │                                context = activity + memory.profile(visitor): returning, upcoming booking, first name, last topic
          │                                first match not in cooldown ──► INSERT outreach_events ──► {rule: {…, event_id}}
          │                                otherwise ──► {rule: null, recheck: {dwell_s, scroll_pct}, default: on/off}
          ├─ at recheck.dwell_s / recheck.scroll_pct ──► POST /outreach/check again
          └─ tap / close ──► POST /outreach/event {event_id, action: opened|dismissed, session_id}
```

* `app/outreach.py`: `normalise` (validation), `path_matches`, `evaluate`, `context`, `render`, `check`, `mark`,
  `stats`, CRUD, `SEED`. Rules are cached in process for 15 s.
* Tables `outreach_rules` and `outreach_events` (`app/db.py`). The activity payload is never stored; a firing
  keeps only the page URL. Opening the chat stamps the session id, which is how chats and bookings are attributed.
* Endpoints: `POST /outreach/check`, `POST /outreach/event` (origin-checked, 60/min per IP);
  `GET /admin/outreach?days=`, `POST/PATCH/DELETE /admin/outreach/rules[/{id}]`, `PUT /admin/outreach/settings`
  (`{"default_greeting": false}`), `POST /admin/outreach/try`.
* `OUTREACH_ENABLED=false` makes `/outreach/check` answer "no rule, generic greeting on", so the loader behaves
  exactly as before. If the server is unreachable the loader also falls back to the generic greeting.
* The event's visitor id must match when it is marked opened or dismissed, so a stranger cannot stamp someone
  else's firing.

## Testing

* `pytest tests/test_outreach.py`: patterns, every trigger kind, waits, templating, validation, cooldown,
  attribution, partial updates, the generic-greeting switch.
* `node scripts/browser_check_widget.mjs http://127.0.0.1:8080 out`: creates a rule that waits 3 s on `/site`,
  sees the generic greeting first, then the rule bubble replacing it, opens the chat from it, checks the console
  counts the open against the chat session, switches the rule off and confirms silence, deletes it.
* By hand: Console → Outreach → Try it with page `/company/lake-b2b` and 60 s; then open
  `https://deependhq.com/company/lake-b2b`, wait 45 s.

## Privacy

The check sends the pages seen in this browser session (paths only), seconds on the page and scroll depth to
the assistant server with the visitor id that the chat already uses. Nothing of that is stored except the page
on which a rule fired. Add one line to the site's privacy text next to the existing tracking disclosure
(`docs/TRACKING.md`): "the assistant also notes which pages you open during a visit so it can offer relevant help".
