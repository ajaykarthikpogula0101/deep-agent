# Emails: who gets what, and how to change the wording

Three emails, all plain text, all rendered from templates you can edit in **Console → Emails** without touching code.

| Email | To | When | Default subject |
|---|---|---|---|
| Host brief | `HOST_EMAIL` | every lead: booking hand-off, API booking, enquiry, human hand-over | `[{brand}] {kind}: {name} · {title} · {date}` |
| Visitor booking confirmation | the visitor | after a booking step (hand-off, booked, enquiry) | `Thank you for booking with {brand}: {title} on {date_visitor}` |
| Visitor hand-over acknowledgement | the visitor | after they ask for a human and submit the form | `Thanks for your message to {brand}` |

Replies to a visitor email go to the host; replies to the host brief go to the visitor.

## Variables

`{brand}` `{title}` `{duration}` `{kind}` `{name}` `{first_name}` `{email}` `{reason}` `{date}` `{date_visitor}`
`{visitor_tz}` `{host_tz}` `{link}` `{next_step}` `{origin}` `{note}` `{host_name}` `{host_email}` `{site}`

* `{brand}` is derived from the call type through the **brand map** (one `keyword=Brand` per line; the first
  keyword found in the call type's name or slug wins), otherwise the **default brand**. With the defaults, a
  "LakeB2B Discovery Call" gives `LakeB2B`; a call type containing "span" gives `SPAN Global Services`; a hand-over
  (no call type) gives `Champions Group`.
* `{title}` is the call type's name. `{date}` is the slot in the host's timezone, `{date_visitor}` in the visitor's.
* `{link}` is the Zoom confirmation link with the visitor's details prefilled (hand-off only).
* `{next_step}` is one sentence that depends on the outcome: confirm on Zoom (hand-off), it's confirmed (API
  booking), the host will confirm by email (enquiry), the host will reply (hand-over).
* An unknown variable renders as nothing. A body line that ends up as only a label (`Note:    `) is dropped.

## Editing

Console → Emails: edit, watch the preview update with a sample booking, **Save templates**. Changes are live within
30 seconds. **Send test** mails each preview to the host inbox. **Reset all to defaults** clears every saved
template. Either visitor email can be switched off with its checkbox.

Templates are stored in the `settings` table under `tpl:*` keys; the defaults live in `app/templates.py`.

## Added 2026-10-06: reminder email and `{company}`

* **Fourth template, `visitor_nudge`** (Console → Emails → "Visitor reminder"): sent once, 24 h after a Zoom hand-off
  that nobody has confirmed, with the same prefilled Zoom link (`{link}`), the wanted time (`{date_visitor}`) and the
  call type (`{title}`). `{next_step}` renders "Confirm it here, your details are already filled in: {link}".
  Switch it off with the checkbox, stop a single lead with "mark confirmed" on its conversation, or set
  `NUDGE_ENABLED=false`. Details and rules: docs/AUTOMATIONS.md §8.
* **New variable `{company}`**: the visitor's company from their email domain (docs/AUTOMATIONS.md §7), e.g.
  `LakeB2B (lakeb2b.com) · B2B data and intent signals`. The default host brief has a `Company:` line that
  disappears when the address is personal (gmail, outlook, …) or the lookup found nothing.
* `send_plain(to, subject, body)` in `app/booking/email.py` sends any other text email; the weekly digest uses it.
  Since 2026-10-13 the digest may add an HTML alternative (`DIGEST_RICH_EMAIL`, docs/AUTOMATIONS.md §6): the text stays
  the `text/plain` part and the fallback; `send_plain`'s signature is unchanged.

## Added 2026-10-07: booking emails from the in-chat picker (docs/BOOKING.md)

* `visitor_confirmed_*` — "Your call with Deep is confirmed: {title} on {date_visitor}" (or "…: one last step" while the
  Zoom confirmation is pending), with `{join_url}`, `{meeting_line}` (Meeting ID · Passcode), `{manage_line}` (cancel /
  reschedule link) and the `.ics` invite attached. Sent as text + an HTML version (since 2026-10-15 the Ledger design, see the last section).
* `host_booking_*` — "[{brand}] New booking: {name} · {title} · {date}" to `HOST_EMAIL`, with company, notes, origin,
  `{method_line}` (Scheduler API / Meetings API / hand-off) and the same invite.
* Both go through `app/mailer.py` (background, 3 attempts with backoff); the booking succeeds even if SMTP is down.
  Console → Emails previews and send-tests both.

## Added 2026-10-13: pre-call brief in the host emails

Deep's "New booking" email now ends with a PRE-CALL BRIEF (lead score with the reasons, a summary, what they asked,
talking points, questions to ask, watch-outs) and names a hot or warm lead in the subject. Two new host emails, not
templated: "Brief for tomorrow: {name} · {lead}" the day before, and "Hot lead, no call booked yet" for a hot visitor
who left an email but booked nothing. In the HTML card, UPPERCASE lines are section headings and "• " lines become a
list. Details and the score rules: docs/AUTOMATIONS.md section 12.

## Added 2026-10-13: lifecycle emails (moved, cancelled, reminder)

Three more visitor emails, all editable in Console → Emails and all with the same warm shape as the booking
confirmation (greeting by first name, a thank-you line, the facts, what happens next, a sign-off):

| Email | Template | When | Default subject |
|---|---|---|---|
| Call moved | `visitor_rescheduled` | after a reschedule from the chat or the manage link (carries the updated .ics) | `Your call with {host_name} has moved: {title} now on {date_visitor}` |
| Call cancelled | `visitor_cancelled` | after a cancel from the chat or the manage link | `Your call with {host_name} is cancelled: {title} on {date_visitor}` |
| Day-before reminder | `visitor_reminder` | `REMINDER_BEFORE_HOURS` (24) before every upcoming booking, once (app/reminders.py) | `Reminder: {title} with {host_name} tomorrow, {date_visitor}` |

New variables: `{old_date}` / `{old_date_visitor}` (the time a moved call had before) and `{booking_link}` (the Zoom
scheduler page). `{next_step}` follows the booking's real state: a confirmed call says "join with the Zoom link", a hold
that still needs confirming on Zoom repeats the prefilled link. The host keeps receiving the short "Moved" / "Cancelled"
notes as before.

### Guests (added 2026-10-13)

`{attendees}` lists the extra guests as "Name <email>, …" (empty when there are none; the "Guests:" line then
disappears). Each guest receives a short built-in note per event: invited, moved, cancelled, day-before reminder
(`app/booking/email.py: attendee_notice`), replies going to the host. Since 2026-10-15 their HTML is the Ledger design.

## Added 2026-10-14: branded HTML for the two in-chat booking emails

* `visitor_confirmed_*` and `host_booking_*` now carry a branded HTML design (status pill, event card,
  attendee/company rows, one button) built by `app/booking/email_html.py`. The **text part is unchanged**: still the
  editable template above, so Console → Emails edits keep working. (The first version had a navy hero and PNG icons;
  since 2026-10-15 every booking email uses the Ledger design instead, see the last section.)
* The host copy keeps everything main added: extra guests get a Guests row, the PRE-CALL BRIEF renders as its own
  section (UPPERCASE headings, fact rows, bullets), and a late "since cancelled / since moved" update shows above the status
  (no button once cancelled).
* The copy follows the real booking status, never the other way round:

  | | `confirmed` (Zoom created the meeting) | `pending_zoom` (time held, visitor must confirm on Zoom) |
  |---|---|---|
  | Visitor | "Your booking is confirmed", Join meeting link, button "View booking details" (manage page) | "Confirm your booking on Zoom", no meeting link, button "Confirm on Zoom" (prefilled link) |
  | Host | "New booking confirmed", Join meeting link, button "View booking details" | "New booking request", "still required to confirm on Zoom" (+ the 24 h reminder line only while reminders are on) |
* Local look without SMTP: `python scripts/preview_booking_email.py` writes every email to `email_preview/` (see the
  last section).

## Added 2026-10-14: answers to unanswered questions, and call outcomes

| Email | To | When | Default subject |
|---|---|---|---|
| Answer to their question | the visitor | 10 min after Deep approves a drafted answer to a question they asked (docs/AUTOMATIONS.md §13) | `Your question, answered: {question_short}` |
| How did the call go? | `HOST_EMAIL` | 20 min after a booked call ends, with four buttons | `[{brand}] How did the call with {name} go? · {title} · {date}` |
| Follow-up after the call | the visitor | only when Deep presses "Send" on the drafted follow-up (§14) | written by the model, edited by Deep |

The answer email is the template `visitor_gap` (Console → Emails), with five extra variables: `{answers}` (their question
in their words and the answer, for each question answered), `{question_short}`, `{asked_date}`, `{chat_link}` (the site
with `utm_campaign=gap-followup`) and `{optout_line}` (the signed unsubscribe link). The other two are not templates: the
outcome email is fixed, and the follow-up is drafted per call.

## Added 2026-10-15: one design for every booking email ("Ledger")

Every booking-lifecycle email now has its HTML part built from one design system in `app/booking/email_html.py`. The
**text parts, subjects, recipients, reply-to, `.ics` attachments, when each email is sent and in what order are
unchanged** (a golden snapshot test, `tests/test_email_golden.py`, holds them to what was sent before).

| # | Email | To | Renderer |
|---|---|---|---|
| 1 | Booking confirmed / request (pending Zoom) | visitor | `render(…, "visitor")` |
| 2 | New booking confirmed / request (+ pre-call brief, late "since cancelled / moved" update) | host | `render(…, "host")` |
| 3, 4 | Booking cancelled | visitor, host | `render_cancelled` |
| 5, 6 | Booking rescheduled | visitor, host | `render_moved` |
| 7 | Day-before reminder | visitor | `render_reminder` |
| 8 | "Brief for tomorrow / your call today" | host | `render_host_brief` |
| 9 | Unconfirmed-hold reminder (`visitor_nudge`, 24 h after an unconfirmed Zoom hand-off) | visitor | `render_nudge` (new HTML part; before it was text only) |
| 10–13 | Guest invited / call moved / call cancelled / day-before reminder | each extra guest | `render_guest` |

Console → Emails → **Send test** shows the same design for `host_booking`, `visitor_confirmed`, `visitor_cancelled`,
`visitor_rescheduled`, `visitor_reminder` and `visitor_nudge`. The hand-off and hand-over acknowledgements stay
text-only; the knowledge-gap answer, the call-outcome question, the hot-lead alert and Console → Bookings → "email it
to me" keep the simple card (`templates.html_wrap`), which is also every Ledger email's fallback if rendering fails.

**The design.** One 600px column on a soft canvas; a header with a monogram tile, the brand (`brand_default`) and an
eyebrow label; one white card with status pills, the heading, the opening paragraphs, the event card (a live-text date
tile whose top strip carries the state colour, then label/value rows), the closing paragraphs with the next step as a
note in the state colour, bulletproof buttons (VML for Outlook), the sign-off; a quiet footer with the sent line.
System fonts, tables and inline styles, two small `<style>` blocks (mobile, dark mode incl. Outlook.com), **no images**
(so blocked images change nothing and `static/email/` and `scripts/build_email_assets.py` are gone). Every email has a
preheader. Times: visitor and guest emails in the visitor's time zone, host emails in the host's with the visitor's
time beside it.

| State | Pill | Colour |
|---|---|---|
| Confirmed | ● Confirmed | green |
| Held, awaiting Zoom | ○ Awaiting Zoom confirmation (alone, or as a second pill next to Rescheduled / Today / You're invited) | amber |
| Cancelled (overrides every other state) | – Cancelled | slate, no strike-through, no join link |
| Rescheduled | ● Rescheduled, with a Was / Now block | violet |
| Reminder | ● Tomorrow / ● Today / ● Upcoming (the call's date against today's in the recipient's zone; #8 follows its subject) | blue |
| Guest invited | ● You're invited (outlined) | violet |

**Wording.** #1 and #2 keep their fixed copy. #3–#13 take their words from the text part itself: its subject line is
the heading (as in the simple card), its paragraphs the lead and closing notes, its `Label:  value` lines the event
card (the call, its time and the Zoom line become the title, the date tile or Was/Now block and the Join row), its
sign-off the sign-off; so a Console → Emails edit shows in both parts. Every link in the text part is a link in the
HTML (a long one reads as host/path); the buttons are exactly those the send functions chose before (Confirm on Zoom /
Join Zoom / Book a new time / Open booking page). A pending email never says "confirmed" and never shows a meeting link.

**Preview.** `python scripts/preview_booking_email.py` runs the real send functions with a capturing mailer, the default
templates and example data, and writes every email × audience × state (plus long-name, many-guest, missing-field and
long-brief cases and the Send test kinds) to `email_preview/` with an `index.html`. Nothing is sent and the database is
not touched.


## Added 2026-10-15: Ask Deep panel in visitor and guest emails

Emails #1, #3, #5, #7, #9 and the four guest notes (#10-#13) end with an **Ask Deep** panel (`email_html.ask_panel`,
built by `app/email_ask.panel` inside each email's HTML try block, so a failure still sends the simple card). Host emails
(#2, #4, #6, #8) have none. HTML only: every plain-text part, subject, recipient, reply-to and attachment is unchanged.

| Email | Questions (state at send time) |
|---|---|
| #1 confirmation | confirmed: prepare · what we'll cover · a different time; held: how to confirm on Zoom · what happens after · a different time |
| #3 cancelled | book a new time · what Deep can help with |
| #5 moved | confirmed: when is it now · prepare · a different time; held: how to confirm · what happens after |
| #7 reminder | confirmed: how to join · prepare · can't make it; held: how to confirm · a different time |
| #9 Zoom reminder | how to confirm · what happens after · what we'll cover |
| #10-#13 guests | what is this call about / when is it now / what happens now · prepare or join (or "is the time set yet?" while held) · the time doesn't work / book my own call |

Each link is signed for that booking, that recipient and that email (`app/email_ask.py`); a guest's link is their own.
Console **Send test** shows the panel with question-only links (prefilled on the page, never sent). Settings:
`EMAIL_ASK_ENABLED`, `EMAIL_ASK_TARGET` (`assistant` = `PUBLIC_BASE_URL/ask`, `site` = deependhq.com's widget),
`EMAIL_ASK_TTL_DAYS`, `EMAIL_ASK_AUTOSEND`, `EMAIL_ASK_BIND_HISTORY`. How the chat and the memory use it: README,
"Ask Deep from a booking email", and docs/MEMORY_VOICE.md.
