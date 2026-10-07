# Session origin tracking

Every chat session is recorded with where it came from. This answers "who is talking to the bot, from where,
and what brought them here", and it puts a one-line origin into the host brief for each lead.

## What is collected, and when

| When | What | Where it goes |
|---|---|---|
| Chat opened (the `/track` beacon) | session id, visitor id, landing page URL, referrer, UTM parameters, browser timezone, language, screen size, user agent, **client IP** | `sessions` row |
| A few hundred ms later (background thread) | country, region, city, lat/lon, ISP, timezone, derived from the IP | same row, `geo_*` columns |
| Every chat message | `last_seen`, `messages` counter (creates the row if the beacon never fired) | same row |
| A lead is saved | `leads.session_id`, `sessions.leads += 1`, origin line in the host brief email | `leads` row, email |
| Daily 03:10 host time | IP and user agent nulled on rows older than `TRACK_RETENTION_DAYS`; geo cache older than 30 days dropped | purge |

**The tracker.** `widget.js` keeps a random visitor id in the **site's** localStorage (`dh_vid`), first party, no
cookie. When the visitor opens the chat it passes that id, the page URL and the referrer to the chat iframe, which
sends one beacon per session. A returning visitor shows as "visit N" and `returning (N)` in the admin view. The id is
random: it identifies the browser profile, nothing else, and it carries no fingerprinting.

**Channel** is derived once per session: `direct`, `internal` (came from another deependhq.com page), `search`,
`social` (LinkedIn, X, YouTube, Reddit, WhatsApp...), `ai` (ChatGPT, Perplexity, Claude, Gemini...), `email`,
`paid` (utm_medium cpc/paid, gclid, fbclid, li_fat_id), `campaign` (utm_source without a referrer), `referral`.

## Reading it

* **Dashboard:** `https://<assistant host>/admin`, paste the admin token. Tiles (sessions, unique visitors, messages,
  leads), chips by country and channel, one row per session with place, network, channel, referrer, landing page,
  new/returning, message count, lead count, IP, device.
* **JSON:** `GET /admin/sessions?days=7&limit=200` with header `X-Admin-Token`.
* **SQL:** `SELECT first_seen, city, country_code, channel, referrer_host, messages, leads FROM sessions ORDER BY first_seen DESC;`
* **Host brief:** every lead email carries a line such as
  `Where:   Bengaluru, Karnataka, IN · Jio · via linkedin.com (social) · on /pillars · visit 2 · 4 messages`.
* **Quick lookup from the shell:** `python -m app.tracking 203.0.113.9`.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TRACKING_ENABLED` | `true` | `false` turns the beacon into a no-op and stops the per-message touch |
| `GEOIP_PROVIDER` | `ipwho` | `ipwho` (ipwho.is, free, no key, HTTPS, ~10k/month), `ipinfo` (token, 50k/month, commercial OK), `ipapi` (ip-api.com, HTTP only, non-commercial), `none` |
| `GEOIP_TOKEN` | | ipinfo token |
| `TRACK_IP_MODE` | `full` | `masked` stores only the /24 (IPv4) or /48 (IPv6) after the geo lookup |
| `TRACK_RETENTION_DAYS` | `90` | after this the IP and user agent are nulled; the geo/channel aggregate stays |
| `TRUST_PROXY` | `true` | honour `CF-Connecting-IP`, `X-Real-IP`, `X-Forwarded-For`. Set `false` only when the app faces the internet directly, otherwise a caller can spoof their IP |
| `ADMIN_TOKEN` | | required for `/admin/*`; empty disables them |

Results per IP are cached in `ip_geo` for 30 days, so the provider sees each address once. Private and loopback
addresses are never sent to the provider (`geo_status=private`), which is what local testing shows.

## Privacy obligations this creates

The site's footer and `/privacy` currently promise "no cookies, no trackers". This feature keeps "no cookies" true
and makes "no trackers" false. Before go-live:

1. Change the footer disclosure (see `docs/WIDGET_SWAP.md`) to: "the Ask Deep chat stores your messages, your IP
   address and approximate location, and the page you came from, to improve answers and to follow up on booking
   requests".
2. Add the same to `/privacy`, with the retention period (`TRACK_RETENTION_DAYS`) and the geo provider named as a
   processor.
3. If the audience includes the EU/UK, consider `TRACK_IP_MODE=masked`, which keeps city-level geo while storing no
   full IP, and keep retention short. Under GDPR an IP address is personal data; a masked one is much easier to
   justify on legitimate interest.
4. `/admin` must sit behind HTTPS and a strong `ADMIN_TOKEN`; it exposes IPs.

## Verifying it locally

```
python scripts/smoke_tracking.py --boot
```

Sends a beacon with a spoofed public `X-Forwarded-For` (allowed because `TRUST_PROXY=true`), two chat messages, and
prints the session row, the origin line, and the admin summary.
