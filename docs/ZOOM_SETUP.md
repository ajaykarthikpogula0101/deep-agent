# Zoom API setup (Server-to-Server OAuth) and what to check now

The bot works today without any of this, through the public endpoint the booking page uses. This gives it the
official, supported path and unlocks booking directly through the API. Someone with **admin rights on Deep's Zoom
account** has to do steps 1-3; it takes about 10 minutes.

## 1. Confirm the licence

Zoom Scheduler must be licensed on the account (it is included in Zoom Workplace Business and above, or sold as an
add-on). Check: Zoom web portal → Account Management → Billing → Plans. If Scheduler is not listed, the API will answer
`401 Invalid license type` and we stay on the fallback.

## 2. Create the app

1. Go to https://marketplace.zoom.us → **Develop** → **Build App** → **Server-to-Server OAuth** → Create.
2. Name: `deependhq-assistant`. Company name and contact: whoever owns it.
3. **App Credentials** tab: copy **Account ID**, **Client ID**, **Client Secret** into `.env` as
   `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET`.
4. **Scopes** tab → Add Scopes → search "scheduler" and tick:
   - `scheduler:read:admin` (lists schedules, reads availability)
   - `scheduler:write:admin` (only needed for booking through the API; harmless to add now)
   If the portal shows granular scopes instead, tick everything under Scheduler that starts with
   `scheduler:read:` and `scheduler:write:`.
5. **Activation** tab → Activate.

## 3. Run the checker

```bash
python scripts/verify_zoom.py
```

It prints four lines. What each outcome means:

| Step | OK means | Failure means |
|---|---|---|
| 1 OAuth token | credentials are right | typo in the three values, or the app is not activated |
| 2 list schedules | licence and scopes are right; it prints the three call types | `Invalid license type` → open a Zoom support ticket quoting developer forum thread 145888; the bot keeps using the fallback meanwhile |
| 3 available_times | prints the three env values to paste into `.env` | none of six parameter-name guesses worked; copy the names from the API reference page |
| 4 public fallback | same slots from the unauthenticated endpoint | the fallback is down too; nothing to do but wait |

## 4. Optional: booking through the API instead of the hand-off

Only after step 3 passes. Make one real test booking:

```bash
python -c "from app.booking.zoom import *; from datetime import *; c=ZoomOfficialClient(); s=[x for x in c.list_schedules() if x.slug=='discovery-call'][0]; sl=c.available(s, datetime.now(timezone.utc), datetime.now(timezone.utc)+timedelta(days=7), 'Asia/Kolkata'); print(c.create_booking(s, sl[0].start_utc, 'Test', 'Booking', 'you@yourmail.com', 'assistant test, please ignore'))"
```

If a Zoom confirmation lands in your inbox, set `ZOOM_ENABLE_API_BOOKING=true` and cancel the test meeting. The bot
will then say "Booked" instead of handing off to the Zoom page.

## Call types

All active schedules on https://scheduler.zoom.us/sreedeep are offered, fetched live and cached for 10 minutes:

| slug | name | length |
|---|---|---|
| `discovery-call` | LakeB2B Discovery Call | 15 min |
| `lakeb2b-product-walkthrough-use-case-demo` | LakeB2B Product Walkthrough & Use Case Demo | 30 min |
| `gtm-strategy-session-data-ai-revenue-acceleration` | GTM Strategy Session: Data, AI & Revenue Acceleration | 45 min |

Renaming or adding a schedule in Zoom needs no code change. Deactivating one hides it from the bot.
