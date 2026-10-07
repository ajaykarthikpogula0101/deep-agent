# In-chat booking (calendar picker, Zoom booking, confirmation emails)

Version 2026.10.07.1. The visitor books Deep entirely inside the chat: call type → date → time → details →
"Confirm booking" → success card with the Zoom link and an "Add to calendar" invite. Both sides get an email with the
.ics attached. Nothing else in the chat changed.

## What Zoom allows (checked 2026-10-07)

* **Scheduler API can create bookings.** `POST /scheduler/attendee` (scope `scheduler:write:scheduled_event:admin`,
  classic `scheduler:write:admin`) takes `schedule_id`, `start_date_time`, `duration`, `booker{email, first_name,
  last_name}`, `location_configuration{kind: "zoomMeeting"}`, `time_zone`. The booking then shows on Deep's scheduler
  like one made on the booking page. Known wrinkle: some accounts get `400 Failed json validation` or `401 Invalid
  license type` on Scheduler endpoints (devforum 144729 / 145888), so there is a fallback.
* **Fallback: Meetings API.** `POST /users/{ZOOM_HOST_USER_ID}/meetings` (scope `meeting:write:meeting:admin`)
  creates the meeting at the chosen time with the visitor as invitee; `DELETE /meetings/{id}`
  (`meeting:delete:meeting:admin`) cancels it. Our `bookings` table marks that slot busy so it shows "Not available"
  in the picker at once.
* **No credentials (today):** the visitor's time is held in the chat and they finish on Deep's booking page with their
  details prefilled (`pending_zoom`). The success card says "One last step on Zoom". The 24 h reminder (docs/AUTOMATIONS.md
  §8) covers people who never click.
* Availability still comes from `GET /scheduler/schedules/{id}/available_times` (official) or the public
  `availableTimes` endpoint the booking page uses (fallback). Both return only OPEN starts, so the picker rebuilds the
  whole day: the working window and the step are inferred from the open slots (or `HOST_HOURS`), every other candidate
  start in that window is "Not available", our own confirmed bookings are "booked", earlier today is "past".

## Flow

```
visitor: "book a call" ──► model calls get_available_slots(slug)
                             ├─ event availability  (14-day grid, visitor tz)      ─► picker card
                             └─ event slots         (3 open slots: model context, legacy page)
visitor taps a date, then an open time ─► details form (name/email hidden when signed in, company, topic)
"Continue" ─► summary card (call, when, duration, who) ─► "Confirm booking"
POST /booking/confirm ─► flow.confirm():
    validate (no placeholders) → per-email active cap (2) → re-check the slot on Zoom + our bookings
    → book: scheduler API → meetings API → prefilled hand-off link
    → store lead (status booked / handoff) + booking row → queue visitor + host emails (.ics) → event
success card: "✅ You're booked with Deep" / "⏳ One last step on Zoom", Join Zoom, Add to calendar, email note
the component appends "Booking confirmed: …" (or "Time held: …") to the model's history: rule 8 keys off that line.
typed time ("book me Friday 4pm") ─► model calls book_slot(start) ─► flow.review(): the time is checked on the live
    grid; 'review' opens the details form for it, 'unavailable' shows the 3 nearest open times. Nothing is booked.
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/booking/availability?schedule=&days=&tz=` | the grid (cached 60 s per slug/tz/days) |
| POST | `/booking/confirm` | the only place a booking is made; rate limited 4/min, 12/day per session; verified identity overrides the form |
| GET | `/booking/{id}/ics?t=` | the invite (token from the email / success card) |
| GET | `/booking/{id}/manage?t=` | simple page: details, join link, cancel button |
| POST | `/booking/{id}/cancel?t=` | cancels on Zoom (Meetings API) and here; emails both sides |
| GET | `/admin/bookings?days=` | console/API list of bookings + mailer stats |
| POST | `/admin/bookings/{id}/cancel` | owner cancels a booking (Zoom meeting deleted when we created it; both sides emailed); the browser suite uses it to clean up |

Responses of `/booking/confirm`: `confirmed`, `pending_zoom`, `slot_taken` (+ `alternatives`), `rate_limited`,
`invalid`, `unavailable` (+ `fallback_link`, `retry`), `error` (+ `retry`).

## Files

* New: `app/booking/availability.py` (grid), `app/booking/flow.py` (review / confirm / cancel), `app/booking/ics.py`,
  `app/mailer.py` (background queue, 3 attempts, 2/8/30 s backoff, results ring buffer), `app/store_bookings.py`.
* Changed: `app/booking/zoom.py` (`create_booking` body per docs + `tz`, `create_meeting`, `delete_meeting`),
  `app/booking/tools.py` (picker event; `book_slot` → review), `app/chat.py` (event list), `app/rag/prompts.py`
  (rules 7 and 8), `app/booking/email.py` (`_send` with HTML + attachments, `send_booking_emails`, `send_cancel_emails`,
  test kinds), `app/templates.py` (templates `visitor_confirmed_*`, `host_booking_*`; variables `headline join_url
  meeting_id passcode meeting_line ics_url manage_url manage_line method_line`; `html_wrap`), `app/config.py`,
  `app/db.py` (table `bookings`), `app/main.py` (endpoints, `ConfirmIn`, demo user from settings),
  `static/deep-assistant.js` (picker, form, summary, success card, CSS), `scripts/browser_check_widget.mjs`.

## Environment

```
ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET   Server-to-Server OAuth app (still pending from Deep's admin)
ZOOM_ENABLE_API_BOOKING=true      book through the Scheduler API when the credentials are set
ZOOM_HOST_USER_ID=                Deep's Zoom user id or email, for the Meetings API fallback
PUBLIC_BASE_URL=                  where this service is reachable; used in the email links (ics / manage)
BOOKING_DAYS_AHEAD=14             picker range          AVAILABILITY_CACHE_SECONDS=60
HOST_HOURS=                       e.g. 09:00-18:00 in HOST_TIMEZONE; empty = inferred from Zoom's open slots
BOOKING_MAX_ACTIVE_PER_EMAIL=2    upcoming bookings one address may hold
SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD (or SMTP_PASS) EMAIL_FROM (or SMTP_FROM) HOST_EMAIL
DEMO_USER_NAME / DEMO_USER_EMAIL  the /demo signed-in visitor (test confirmations go to that address)
```

Zoom app scopes to request (Server-to-Server OAuth, Marketplace → Scopes):
`scheduler:read:schedules:admin`, `scheduler:read:availability:admin` (or classic `scheduler:read:admin`),
`scheduler:write:scheduled_event:admin` (classic `scheduler:write:admin`), `meeting:write:meeting:admin`,
`meeting:delete:meeting:admin`, `user:read:user:admin` (to resolve `ZOOM_HOST_USER_ID`).

## Database

Table `bookings` (created by `init_schema`): id, created_at, lead_id, session_id, name, email, company, notes,
schedule_slug, schedule_name, duration_min, start_utc, end_utc, visitor_tz, method (`scheduler | meeting | handoff`),
zoom_meeting_id, join_url, passcode, zoom_event_id, handoff_url, status (`confirmed | pending_zoom | cancelled`),
manage_token, cancelled_at, origin, company_line, zoom_error. Every booking also creates a `leads` row (status
`booked` or `handoff`) so the console, digest and nudges keep working.

## Testing end to end

1. Start Postgres and the server (`docs/TEST_SETUP.md`), open `http://localhost:8080/demo` (signed in as the demo
   user, whose email is `DEMO_USER_EMAIL`, set to a plus-address of your own Gmail) or `/site`.
2. Type "I want to book a call". Pick a call type → the date row and time grid appear ("Times shown in …"); taken
   times are greyed and struck through, empty days are greyed.
3. Pick an open time → details form (email hidden for the signed-in demo user) → Continue → summary → **Confirm booking**.
4. Without Zoom credentials you get "⏳ One last step on Zoom" with a prefilled Zoom button, "Add to calendar"
   (downloads the .ics) and the email note. With credentials you get "✅ You're booked with Deep" and "Join Zoom".
5. Check your inbox: visitor email "Your call with Deep is confirmed: …" (or "…: one last step") with `invite.ics`,
   and the host email "[Brand] New booking: …" at `HOST_EMAIL`, also with the invite. Console → Emails previews both.
6. **Double-booking check:** open a second browser (or incognito) at `/site`, book the SAME time. With API booking
   the second confirm returns `slot_taken` and shows the nearest open times; without credentials both are held
   (`pending_zoom`), which is by design: only a confirmed Zoom booking blocks a slot. To see the overlay without
   credentials: `UPDATE bookings SET status='confirmed', method='meeting' WHERE id=<first>;` then reload the picker:
   the time shows "Not available (Already booked)" and a confirm attempt returns `slot_taken`.
7. Typed time: say "book me the discovery call on Friday at 4pm". The model calls `book_slot`; if 16:00 is open the
   details form appears for it, otherwise "… is not open" with the three nearest times.
8. Cancel: click the manage link in the visitor email → Cancel. Both sides get "Cancelled: …"; the Zoom meeting is
   deleted when we created it (Meetings API), a note asks Deep to cancel manually for Scheduler-API bookings.
9. Automated: `pytest tests/test_inchat_booking.py` (grid, review, scheduler → meetings → hand-off fallback,
   slot_taken, rate limit, placeholders, Zoom down, cancel, .ics, emails, mailer retries) and
   `node scripts/browser_check_widget.mjs http://127.0.0.1:8080 out` (real picker → confirm → success card → bookings row).

## Limits and notes

* Reschedule = cancel + pick a new time in the chat (the manage page links to the site). Scheduler-API bookings
  cannot be cancelled through the API yet; the host email says so.
* `pending_zoom` bookings do not block the slot for other visitors (the time is not reserved on Zoom); they are
  listed in the console and reminded after 24 h.
* The legacy `/legacy` page still renders the 3-slot buttons from the `slots` event; it does not get the picker.
