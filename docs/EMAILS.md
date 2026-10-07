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

## Added 2026-10-07: booking emails from the in-chat picker (docs/BOOKING.md)

* `visitor_confirmed_*` — "Your call with Deep is confirmed: {title} on {date_visitor}" (or "…: one last step" while the
  Zoom confirmation is pending), with `{join_url}`, `{meeting_line}` (Meeting ID · Passcode), `{manage_line}` (cancel /
  reschedule link) and the `.ics` invite attached. Sent as text + a dark/orange HTML version (`templates.html_wrap`).
* `host_booking_*` — "[{brand}] New booking: {name} · {title} · {date}" to `HOST_EMAIL`, with company, notes, origin,
  `{method_line}` (Scheduler API / Meetings API / hand-off) and the same invite.
* Both go through `app/mailer.py` (background, 3 attempts with backoff); the booking succeeds even if SMTP is down.
  Console → Emails previews and send-tests both.
