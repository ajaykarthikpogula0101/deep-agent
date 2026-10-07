# Test setup: deependhq.com knowledge base + your own Zoom schedule + your own inbox

Nothing here touches Deep's Zoom account or inbox. Three things to fill in `.env`, then four commands.

## A. Your Zoom schedule (5 minutes)

1. Sign in at https://zoom.us → left menu **Scheduler** (or https://scheduler.zoom.us). If you do not see it, your
   plan has no Scheduler licence; the free trial works for testing.
2. **Create** → **Booking schedule** → one host (you) → name it e.g. `Test call`, 15 minutes, availability Mon-Fri,
   leave the rest default → Save.
3. Open your booking page: Scheduler → **Share** or the link under the schedule. It looks like
   `https://scheduler.zoom.us/<your-handle>/test-call`. The part after `scheduler.zoom.us/` and before the next `/`
   is your handle.
4. In `.env` set `ZOOM_BOOKING_USER=<your-handle>` and `ZOOM_BOOKING_BASE=https://scheduler.zoom.us/<your-handle>`.
5. Check it is public: open `https://scheduler.zoom.us/<your-handle>` in a private window. You should see your
   schedule without logging in.

## B. Email to your inbox (5 minutes)

`championsmail.com` is on Google Workspace, so Gmail's SMTP server works with an app password:

1. https://myaccount.google.com/security → turn on 2-Step Verification if it is off.
2. https://myaccount.google.com/apppasswords → app name `deependhq-assistant` → Create → copy the 16 characters.
   (If the page says app passwords are not available, your Workspace admin has disabled them; use a personal Gmail
   for the test and set `SMTP_USER`, `EMAIL_FROM` and `HOST_EMAIL` to it.)
3. In `.env` set `SMTP_PASSWORD=<those 16 characters, no spaces>`.

## C. Groq key, free (2 minutes)

The chat model runs through OpenRouter (`openai/gpt-4.1-mini` by default; any tool-capable model on
https://openrouter.ai/models works, change `CHAT_MODEL` in `.env`). Embeddings run locally with a Hugging Face model,
so no other key is needed.

1. https://console.groq.com → sign up (Google login works) → **API Keys** → **Create API Key** → name it
   `deependhq-assistant` → copy the key (starts with `gsk_`).
2. Paste it into `.env` on the `LLM_API_KEY=` line, replacing `FILL_ME`.

Free-tier limits are per minute and per day; enough for the demo. If the bot ever answers "hit its daily budget" or
the OpenRouter key hits its weekly limit (`GET https://openrouter.ai/api/v1/auth/key` shows `limit_remaining`), switch
`CHAT_MODEL` to a `:free` model such as `nvidia/nemotron-3-super-120b-a12b:free` until it resets.

## Before you run it: free some space on C:

On 2026-10-05 drive C: had 0 MB free (D: has 77 GB). Postgres, pip and the crawler all write to C:. Options, safest
first: Docker Desktop → Settings → Resources → Advanced → "Disk image location" → move to D:; empty the Recycle Bin and
`%TEMP%` (2.5 GB); `docker builder prune` (611 MB of old build cache).

## Run it

```powershell
# the virtualenv lives on D: because C: is full
$env:OPENBLAS_NUM_THREADS="1"
docker compose up -d db                                   # 1. database
D:\deependhq-venv\Scripts\python.exe scripts\test_email.py           # 2. one sample brief lands in your inbox
D:\deependhq-venv\Scripts\python.exe scripts\smoke_booking.py        # 3. your call types + live slots (NY and IST times)
D:\deependhq-venv\Scripts\python.exe scripts\smoke_booking.py book test-call   # 4. full booking: brief emailed + Zoom link
D:\deependhq-venv\Scripts\python.exe -m app.ingest.pipeline          # 5. crawl + embed deependhq.com (free, local model)
D:\deependhq-venv\Scripts\python.exe -m uvicorn app.main:app --port 8080   # 6. open http://localhost:8080 and chat (needs the Groq key)
```

In the chat, try: "what did Deep ship on day 338?", "which companies are in Champions Group?", "book a call",
then pick a call type and a slot, give a name/email/reason, and click **Confirm on Zoom**. The brief arrives in your
inbox before the Zoom page even opens.

## What to look at

* Inbox: subject `[deependhq assistant] Demo request (handing off to Zoom): <name>` with call, reason, both timezones.
* Zoom page: first name, last name and email already filled in, month preselected.
* Zoom Scheduler → Scheduled events: the test meeting after you confirm it on the Zoom page. Delete it afterwards.
* `http://localhost:8080/healthz`: spend so far today.
