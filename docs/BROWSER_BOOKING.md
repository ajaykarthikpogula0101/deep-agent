# Browser booking on Zoom Scheduler (version 2026.10.12.1)

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
  invite. Hand-off bookings (the old path) get a new held time and a new prefilled link.
* **Cancel.** The cancel link in the email now also cancels the Zoom event for browser-made bookings.

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

## Testing, and what has been verified so far

* `pytest tests/test_browser_booking.py` (8): slot-label matching in both clocks and date orders, verification,
  goals, link capture, the subprocess runner (timeouts, bad output), and the flow: booking through the worker with
  links stored, fall back to the hand-off link, taken slots, reschedule (browser and hand-off), cancel, the emails.
* **Live dry run on Deep's real page (2026-10-12, script driver, no key):** picked "Select slot on 15/10/2026,
  16:30:00", filled first name, last name, email and notes, stopped before Book, 28 s. Nothing was booked.
  ```
  python scripts/zoom_browser_worker.py --task book --payload-file dryrun.json     # with "dry_run": true
  ```
* **Not yet verified, needs a test schedule:** pressing Book (the page carries reCAPTCHA Enterprise, which may
  challenge a headless browser), the confirmation page wording and its reschedule/cancel links, and the
  reschedule/cancel pages themselves. Do the first real run against a schedule in **your own** Zoom account
  (`ZOOM_BOOKING_TEST_URL`), never against Deep's calendar:
  ```
  python scripts/zoom_browser_worker.py --task book --payload-file live.json       # "url": ZOOM_BOOKING_TEST_URL, "dry_run": false
  python scripts/zoom_browser_worker.py --task reschedule --payload-file move.json # "url": the reschedule link from the result
  python scripts/zoom_browser_worker.py --task cancel --payload-file cancel.json   # "url": the cancel link
  ```
  If the confirmation wording differs from what `verify_text` expects, adjust `BOOKED_RE` / `RESCHEDULED_RE` /
  `CANCELLED_RE` in the worker; the page text of every run is in the result (`page_text`).
* The jev driver needs `TYPESAFE_API_KEY`; run the same dry run with `"driver": "jev"` first.

## Limits and safety

* One run at a time per booking; the confirm endpoint waits for the worker (up to `BROWSER_BOOKING_TIMEOUT`).
* The worker never retries a click. If the page changes under it, the step is abandoned and the flow falls back to
  the hand-off link, so a visitor never ends up with two bookings.
* Zoom's scheduler page is a product Zoom can change. The worker fails closed: no confirmation text, no booking
  recorded as confirmed. Check Zoom's terms for automated use of the booking page before go-live; the proper
  long-term path remains the Scheduler API with server-to-server credentials, which the same flow prefers whenever
  they are present.
