# Browser booking on Zoom Scheduler (version 2026.10.12.1, live since 2026-10-12)

Bookings and reschedules completed on Deep's **public** scheduler page by a browser worker, so the chat can confirm a
time without Zoom API credentials. The worker is built on [jev-ultrafast](https://github.com/browser-use/jev-ultrafast)
(Browser Use × TypeSafe): a browser agent that reads the page as a numbered table of controls and lets a small
model pick one operation and one element per step. Nothing the model says ever becomes a selector or code; the
executor only acts on elements it observed.

## What changes for the visitor

* **Booking.** "Confirm booking" now ends with "You're booked" and the Zoom link, instead of "One last step on Zoom".
  Both confirmation emails come from the assistant as before, and Zoom sends its own invite too. It takes 20 to 60
  seconds; the card says so while it works.
* **Reschedule.** A returning visitor with an upcoming call sees "Reschedule your call" on the welcome screen, and
  typing "reschedule my call" or "move my meeting" opens the same picker. Two steps: pick a new time, confirm. The
  worker moves it on Zoom through the scheduler's own reschedule link; both sides get a "Moved:" email with a fresh
  invite. A hand-off booking (a time held before the worker existed, never confirmed on Zoom) is moved by booking the
  new time on Zoom for real, so it becomes a confirmed browser booking; only if the worker is unavailable does it fall
  back to re-holding the time with a new prefilled link. The visitor is never sent to Zoom or to their email to do it.
  The picker opens from the welcome screen, from "Need a different time?" under the booking card, and from typing
  "reschedule my call" (also right after booking in the same chat).
* **Cancel.** "Cancel your call" on the welcome screen, "Cancel this booking" under the booking card, or typing
  "cancel my call": the chat asks for confirmation (Yes, cancel it / Keep it), then cancels it on Zoom through the
  worker for browser-made bookings (Meetings-API bookings through the API; hand-off holds simply end), shows "Your
  call is cancelled" with a "Book a new time" button, and both sides get the cancellation email. The email link
  still works too. `DELETE /booking/{id}` (visitor-owned or manage token).

Order of attempts in `flow._book_on_zoom`: Zoom Scheduler API → Meetings API → **browser worker** → prefilled hand-off
link. The worker is used only when `BROWSER_BOOKING_ENABLED=true`.

## How a booking run works (`scripts/zoom_browser_worker.py`)

```
app (Python 3.11)                      worker (Python 3.12, jev environment)
flow.confirm ──► browser_booking.book ──► subprocess: zoom_browser_worker.py --task book --payload-file …
                                          1. launch a headless Chrome/Edge on its own profile (or use JEV_CDP_URL)
                                             and point browser-harness at it (BU_CDP_URL)
                                          2. open the schedule page with the host timezone and en-GB locale emulated,
                                             viewport 1120×1240 so the Book button below the fold is observable
                                          3. select the slot by code: labels read "Select slot on 15/10/2026, 16:30:00";
                                             other weeks via the month calendar ("Choose Thursday, October 15th, 2026")
                                          4. drive the form
                                               jev:    goal = "Book the meeting on …; fill first name 'Ada' …; click Book once …"
                                               script: fill First Name / Last Name / Email Address / notes by label, click Book
                                          5. verify from the page text (confirmation wording + "October 15" + "16:30"
                                             or "4:30"), capture reschedule / cancel / join links, screenshot
                 ◄── one JSON line ──────  {"ok": true, "status": "booked", "links": {…}, "steps": […], "elapsed_ms": …}
```

`dry_run: true` fills the form and stops before Book (status `dry_run_ok`). A `DONE` from the model is never taken as
proof: step 5 decides. `slot_unavailable` comes back before any model call when the time is not on the page, and the
flow then shows the visitor the nearest open times, exactly like a taken slot.

Reschedule and cancel runs open the links captured at booking time (`bookings.zoom_reschedule_url`,
`bookings.zoom_cancel_url`) and use the same drivers.

### Drivers

| `BROWSER_BOOKING_DRIVER` | What drives the form | Needs |
|---|---|---|
| `auto` (default) | `jev` when `TYPESAFE_API_KEY` is set, else `script` | |
| `jev` | TypeSafe's Jev chooses operations and elements; a small text model types values | `TYPESAFE_API_KEY`, a text-model key (defaults to the chat key via OpenRouter) |
| `script` | code fills the known fields and clicks Book; no model at all | nothing |

Both share the slot selection and the verification. `jev` copes with changes to the form (a new required question,
a renamed button); `script` is the deterministic fallback and what runs today until the TypeSafe key arrives.

## Setup

1. **A Python 3.12 environment with jev** (the app itself stays on 3.11):
   ```
   uv venv --python 3.12 D:\jev\venv
   uv pip install --python D:\jev\venv\Scripts\python.exe "jev-ultrafast @ git+https://github.com/browser-use/jev-ultrafast" tzdata
   ```
   On Linux: `/opt/jev/venv` and `google-chrome-stable` installed. The app finds the interpreter through `JEV_PYTHON`
   (defaults: `D:\jev\venv\Scripts\python.exe`, `/opt/jev/venv/bin/python`).
2. **`.env`**
   ```
   BROWSER_BOOKING_ENABLED=true
   BROWSER_BOOKING_DRIVER=auto
   TYPESAFE_API_KEY=                     # from https://docs.typesafe.ai; empty = script driver
   TEXT_MODEL=openai/gpt-4.1-mini        # the model that types field values for jev (OpenRouter); inception/mercury-2.5 is jev's default
   BROWSER_BOOKING_TIMEOUT=150
   JEV_BROWSER_PATH=                     # Chrome/Edge binary; empty = auto-detect
   JEV_CDP_URL=                          # an always-on automation browser (http://127.0.0.1:9222); empty = one per run
   ```
3. Restart. `GET /widget-config` now reports `"booking_mode": "browser"`, and the card shows the longer wait notice.

The worker launches its own headless browser per run on a throw-away profile and removes it afterwards.
browser-harness telemetry and update checks are switched off (`BH_TELEMETRY=0`, `BH_UPDATE_CHECK=0`). Runs leave a
screenshot of the final page under `uploads/zoom-runs/` and a summary on the booking row (`bookings.zoom_run`).

## Verified live (2026-10-12, Deep's real scheduler, authorised by the user)

| Run | Result | Time |
|---|---|---|
| Dry runs (script and jev drivers) | slot picked, four fields filled, stopped before Book | 28 s / 34 s |
| Booking (jev) | "Confirmed. You are booked with Sreedeep Surapaneni ... Friday, October 23, 2026, 21:30 - 21:45"; reCAPTCHA Enterprise did not challenge | 42 s |
| Reschedule through the manage link (jev) | "Confirmed. Your appointment ... has been rescheduled. ... Thursday, October 22, 2026, 21:00 - 21:15"; the typed reason appeared in Zoom's email | 114 s |
| Cancel through the manage link (jev) | "Your appointment with Sreedeep Surapaneni has been canceled." (Cancel, then Cancel Appointment) | 104 s |
| Full cycle on captured links only | booked, moved, cancelled, each verified; calendar clean afterwards | 100 + 102 + 86 s |

Facts about Zoom's pages the worker relies on:

* The confirmation page's Reschedule and Cancel are **buttons**, not links. Pressing Reschedule navigates to
  `https://scheduler.zoom.us/manage/<token>/rescheduling`; the worker records that URL and the bare manage URL
  (`/manage/<token>`), then goes back. Cancel is never pressed during capture.
* **Every reschedule issues a new token and retires the old one.** A retired link shows "This event is no longer
  active ... may have been canceled or rescheduled"; the worker reports `link_expired`, never success, and after a
  reschedule it captures the fresh link, which the app stores on the booking row.
* The manage page offers Reschedule (opens the same calendar) and Cancel (an inline form with an optional reason and a
  "Cancel Appointment" button).
* Zoom's page drew its slots in about 3 s in the morning and 20 to 35 s in the evening; the worker waits for them.

### Speed

browser-harness keeps one daemon per name, bound to the browser it first connected to, and a fresh daemon costs 11 to
12 s. The app therefore keeps **one headless browser per process** (`JEV_PERSISTENT_BROWSER=true`, default) and hands
its address to the worker as `JEV_CDP_URL`; the daemon then survives between runs and a run opens the page in a few
seconds. With `JEV_PERSISTENT_BROWSER=false` the worker launches a browser per run and stops the daemon around it. On a
server, pointing `JEV_CDP_URL` at a supervised headless Chrome works the same way.

## Testing

* `pytest tests/test_browser_booking.py`: slot-label matching in both clocks and date orders, verification (including
  the retired-link page), goals, link capture, the subprocess runner, and the flow: booking through the worker with
  links stored, fall back to the hand-off link, taken slots, reschedule (browser and hand-off, fresh links stored),
  cancel, the emails.
* Dry runs never press a final button: `python scripts/zoom_browser_worker.py --task book --payload-file p.json` with
  `"dry_run": true`, or `browser_booking.book(..., dry_run=True)` from the app.
* **The widget browser suite refuses to run against a server in browser-booking mode** (it would book on the real
  calendar). Start test servers with `BROWSER_BOOKING_ENABLED=false`.
* Every run leaves a screenshot under `uploads/zoom-runs/` and a step list with elapsed seconds in the result
  (`bookings.zoom_run` on the row).

## Limits and safety

* One run at a time per booking; the confirm endpoint waits for the worker (up to `BROWSER_BOOKING_TIMEOUT`).
* The worker never retries a click. If the page changes under it, the step is abandoned and the flow falls back to
  the hand-off link, so a visitor never ends up with two bookings.
* Zoom's scheduler page is a product Zoom can change. The worker fails closed: no confirmation text, no booking
  recorded as confirmed. Check Zoom's terms for automated use of the booking page before go-live; the proper
  long-term path remains the Scheduler API with server-to-server credentials, which the same flow prefers whenever
  they are present.
