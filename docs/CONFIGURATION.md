# Configuration, go-live and deploy

Every setting in `.env`, the checks before going live, and how to run it on a server. The [README](../README.md) has the quick start.

## Configuration

All settings live in `.env`. `.env.example` lists the usual options with a comment; every setting and its default is in
`app/config.py`.

**Core**

| Setting | Default | Purpose |
|---|---|---|
| `LLM_API_KEY`, `LLM_BASE_URL`, `CHAT_MODEL` | | the chat model (Groq, OpenRouter, OpenAI…) |
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | local embedding model |
| `DATABASE_URL` | local Postgres | Postgres with the `vector` extension |
| `SITE_BASE_URL`, `RECRAWL_CRON`, `RECRAWL_TZ` | deependhq.com, `30 2 * * *`, `Asia/Kolkata` | what is crawled and when |
| `RETRIEVAL_MIN_SCORE`, `RETRIEVAL_SOFT_FLOOR`, `RETRIEVAL_TOP_K`, `CUSTOM_ANSWER_MIN_SCORE` | `0.60`, `0.50`, `6`, `0.86` | how close a page or custom answer must be (between the two floors the model decides) |
| `MULTILINGUAL` | `true` | answer in the visitor's language |

**Security and links**

| Setting | Default | Purpose |
|---|---|---|
| `ALLOWED_ORIGINS` | deependhq.com, www | sites allowed to embed the assistant (no wildcard) |
| `ADMIN_TOKEN` | | protects `/admin` and every `/admin/*` endpoint; empty disables them |
| `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_PER_DAY`, `DAILY_SPEND_CAP_USD`, `MAX_MESSAGE_CHARS` | `20`, `200`, `5.0`, `1500` | abuse and cost limits |
| `PUBLIC_BASE_URL` | | the public https address of this service; every email button points here |
| `LINK_SECRET` | | signs the one-tap links in emails (host booking page, outcome buttons, unsubscribe); empty = derived from `ADMIN_TOKEN`, so rotating that token would break every link already sent |
| `TRUST_PROXY` | `true` | read the visitor's IP from forwarding headers… |
| `TRUSTED_PROXIES` | private ranges + loopback | …but only from these peers (add Cloudflare's ranges if it connects directly) |
| `WIDGET_SIGNING_SECRET`, `CLERK_JWT_ISSUER_DOMAIN` | | signed-in visitors from a host app ([WIDGET](WIDGET.md)) |
| `WIDGET_DEMO` | `true` in code, `false` in `.env.example` | the `/demo` page with a sample signed-in user; off in production |
| `PRIVACY_URL` | deependhq.com/privacy | footer link in the widget |

**Booking and email**

| Setting | Default | Purpose |
|---|---|---|
| `ZOOM_BOOKING_BASE`, `ZOOM_*` | | Deep's scheduler page; S2S OAuth credentials for the official API ([ZOOM_SETUP](ZOOM_SETUP.md)) |
| `HOST_TIMEZONE`, `HOST_HOURS`, `BOOKING_DAYS_AHEAD`, `BOOKING_MAX_ACTIVE_PER_EMAIL` | `Asia/Kolkata`, inferred, `14`, `2` | the in-chat picker |
| `BROWSER_BOOKING_ENABLED`, `JEV_*`, `TYPESAFE_*` | `false` | booking on the public Zoom page by a browser worker ([BROWSER_BOOKING](BROWSER_BOOKING.md)) |
| `ZOOM_LINK_FROM_EMAIL`, `ZOOM_LINK_MAILBOX`, `ZOOM_LINK_IMAP_*`, `ZOOM_LINK_WAIT_SECONDS` | `true`, SMTP account, `imap.gmail.com`, `90` | the join link for browser bookings, read from Zoom's invitation |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` | | outgoing mail |
| `HOST_EMAIL` | `deep@championsmail.com` | Deep's inbox: briefs, alerts, digest, outcome questions. Every host email links the host booking page |
| `EMAIL_ASSETS_URL` | jsDelivr copy of `static/email` | public https folder for email images; empty = embed them in each message. No current email uses images |

**Tracking and IP lookup** ([TRACKING](TRACKING.md))

| Setting | Default | Purpose |
|---|---|---|
| `TRACKING_ENABLED` | `true` | session origin tracking on or off |
| `GEOIP_PROVIDER` | `ipwho` | `ipwho`, `ipinfo`, `ipapi`, `ipapiis`, `mmdb`, `none`, or a chain such as `mmdb,ipwho` |
| `GEOIP_TOKEN` | | ipinfo only |
| `MAXMIND_ACCOUNT_ID`, `MAXMIND_LICENSE_KEY` | | download the GeoLite2 files for `mmdb`; empty key = nothing is downloaded |
| `GEOIP_MMDB_DIR` | `data/geoip` once a key is set | where the GeoLite2 files live |
| `GEOIP_DAILY_CAP`, `GEOIP_FAIL_RETRY_MIN` | `300`, `60` | lookups per remote provider per day; minutes before a failed network is retried |
| `GEOIP_DEV_IP` | | local development only: look up this public IP instead of 127.0.0.1 |
| `NET_RDNS` | `false` | reverse DNS on public IPs (only the domain is kept) |
| `NET_SCORE` | `true` | the network rules in the lead score |
| `TRACK_IP_MODE` | `full` | `masked` stores only the /24 (IPv4) or /48 (IPv6); recommended |
| `TRACK_RETENTION_DAYS` | `90` | when IPs and user agents are nulled and idle visitor rows deleted |

**Outreach and returning visitors** ([OUTREACH](OUTREACH.md))

| Setting | Default | Purpose |
|---|---|---|
| `OUTREACH_ENABLED` | `true` | greeting rules from the console |
| `EMAIL_ASK_ENABLED`, `EMAIL_ASK_TARGET` | `true`, `assistant` | the Ask Deep panel in visitor and guest emails; `site` opens deependhq.com's widget instead of `/ask` |
| `EMAIL_ASK_TTL_DAYS`, `EMAIL_ASK_AUTOSEND`, `EMAIL_ASK_BIND_HISTORY` | `30`, `true`, `true` | link lifetime after the call; send the tapped question; join the booker's earlier chats to the new device's memory |
| `OUTREACH_VISITORS` | `true` | a `visitors` row per device for page views without a chat |
| `OUTREACH_VISIT_GAP_MIN` | `30` | minutes without a check before the next counts as a new visit |
| `OUTREACH_IP_CONTEXT` | `true` | hard switch for organisation and country in pop-ups (the console has a soft one) |
| `OUTREACH_COMPANY_KINDS` | `corporate` | network kinds that can be named without approval |
| `OUTREACH_COUNTRY` | `true` | `{country}` in pop-ups |
| `OUTREACH_NO_PERSONALISE_COUNTRIES` | EEA + GB + CH | no network context there; clear it only with a consent banner |
| `OUTREACH_HONOR_GPC` | `true` | Global Privacy Control / Do Not Track: no visitors row, no lookup, no context |
| `OUTREACH_GEO_DAILY_CAP` | `150` | page-view lookups per day (also counted against `GEOIP_DAILY_CAP`) |
| `OUTREACH_DISMISS_QUIET_DAYS` | `14` | quiet days after a "never chatted" pop-up is closed |

**Memory** ([MEMORY_VOICE](MEMORY_VOICE.md))

| Setting | Default | Purpose |
|---|---|---|
| `VISITOR_MEMORY` | `true` | return-visitor memory: greeting, HISTORY, booking facts |
| `WORKING_MEMORY` | `true` | CURRENT CONVERSATION notes and their extraction |
| `MEMORY_EXTRACT` | `true` | the small-model extraction; `false` = rules only |
| `MEMORY_MODEL`, `MEMORY_MODEL_TIMEOUT`, `MEMORY_MODEL_MAX_TOKENS` | `CHAT_MODEL`, `8`, `300` | the extraction model (raise tokens to 800+ for a reasoning model) |
| `MEMORY_MAX_CHARS`, `MEMORY_HISTORY_MAX_CHARS`, `MEMORY_HISTORY_SESSIONS` | `1200`, `1400`, `4` | size of the two blocks and how many earlier conversations |
| `MEMORY_STALE_DAYS`, `MEMORY_RETENTION_DAYS` | `90`, `365` | "may be out of date" marker; purge age |

**Pre-call brief and lead score** ([AUTOMATIONS §12](AUTOMATIONS.md))

| Setting | Default | Purpose |
|---|---|---|
| `PRECALL_ENABLED`, `PRECALL_USE_MODEL`, `PRECALL_MODEL`, `PRECALL_MODEL_TIMEOUT`, `PRECALL_HOST_REMINDER` | on, on, `CHAT_MODEL`, `25`, on | the brief and its day-before email |
| `HOT_LEAD_ALERTS`, `HOT_LEAD_SCORE` | `true`, `60` | alerts for hot leads with no call |
| `SCORE_CALL_TYPES` | demo 10, GTM 8, discovery 0 | points per Zoom call type (`slug:points`) |
| `SCORE_INTERNAL_DOMAINS`, `SCORE_INTERNAL_EMAILS` | Champions Group domains | staff and test addresses (−50, never learned from) |
| `SCORE_COMPETITOR_DOMAINS` | ZoomInfo, Apollo, Lusha… | competitor addresses (−20) |
| `SCORE_TARGET_COUNTRIES` | | ISO2 list for +5; empty = rule off |
| `SCORE_BRANDS` | | extra brand names for the "personal email claims a brand" check |
| `SCORE_KEY_PAGES` | `/pricing,/plans,/contact,/request-demo,/company/lake-b2b` | pages on deependhq.com worth +5 |
| `DOMAIN_CHECK`, `DOMAIN_CHECK_FALLBACK_NS` | `true`, `1.1.1.1,8.8.8.8` | DNS check of business email domains |
| `OUTCOMES_ENABLED`, `OUTCOME_ASK_AFTER_MINUTES` | `true`, `20` | "How did the call go?" |
| `SCORE_LEARNING`, `SCORE_LEARN_MIN` | `true`, `20` | learn from outcomes once this many calls are rated |

**Other automations and media**

| Setting | Purpose |
|---|---|
| `DIGEST_*` | weekly digest and its rich HTML version |
| `NUDGE_ENABLED`, `NUDGE_AFTER_HOURS`, `REMINDER_ENABLED`, `REMINDER_BEFORE_HOURS` | follow-up nudge and day-before reminder |
| `GAP_*` | the knowledge-gap loop ([AUTOMATIONS §13](AUTOMATIONS.md)) |
| `ENRICH_ENABLED`, `SUGGESTIONS_DAYS` | lead enrichment and smart suggestions |
| `STT_*`, `TTS_*`, `VOICE_LANGUAGES` | speech in and out (`browser` or `openai`, i.e. any `/audio/*` endpoint) |
| `UPLOAD_DIR`, `UPLOAD_MAX_MB`, `GIF_PROVIDER`, `GIF_API_KEY` | attachments and GIFs |
| `UI_CARDS_*` | answer cards ([UI_CARDS](UI_CARDS.md)) |

> [!IMPORTANT]
> Never commit `.env`; it is in `.gitignore`. Set long random values for `ADMIN_TOKEN`, `WIDGET_SIGNING_SECRET` and
> `LINK_SECRET` in production. API keys (LLM, Zoom, MaxMind) belong only in `.env` or your host's secret store.

## Go-live checklist

1. **Install the current requirements** on the server: `pip install -r requirements.txt` (it now includes `dnspython`
   for the email domain check and `maxminddb` for the GeoLite2 files).
2. **`HOST_EMAIL`** is Deep's real inbox. Every host email carries the booking-page link, a long-lived key to the
   lead's data.
3. **`PUBLIC_BASE_URL`** is the public **https** address of this service. With `http://localhost:8080` or a private
   address no email button opens on a phone; with plain http the link tokens travel unencrypted.
4. **`LINK_SECRET`** is set to a long random string, so rotating `ADMIN_TOKEN` later does not break links already sent.
5. **`ADMIN_TOKEN`** is long and random, and `/admin` is only reachable over HTTPS (it shows IPs).
6. **`ALLOWED_ORIGINS`** lists exactly the site's origins, and **`WIDGET_DEMO=false`**.
7. **The proxy passes the real visitor IP.** Behind nginx:
   ```nginx
   proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   proxy_set_header CF-Connecting-IP "";   # nginx would otherwise pass on a header the visitor sent
   ```
   If Cloudflare connects to the app directly, add Cloudflare's IP ranges to `TRUSTED_PROXIES`.
8. **IP lookups:** `GEOIP_PROVIDER=mmdb,ipwho` with `MAXMIND_ACCOUNT_ID` and `MAXMIND_LICENSE_KEY`, then
   `python -m app.geoip_update` once; `TRACK_IP_MODE=masked`.
9. **Privacy notice** updated: the chat's tracking, page views without a chat, the lookup providers and the retention
   period (wording in [TRACKING](TRACKING.md#privacy-obligations-this-creates)), plus the MaxMind credit line:
   "This product includes GeoLite2 data created by MaxMind, available from https://www.maxmind.com".
10. **SMTP works:** Console → Emails → Send test `host_booking`; its button opens `/host/booking/sample`.
11. **Restart**, then read the startup log. It warns about each of these when they are wrong: `PUBLIC_BASE_URL` not
    public or plain http, `LINK_SECRET` not set, `dnspython` missing, a MaxMind key without `mmdb` in
    `GEOIP_PROVIDER`, and GeoLite2 files or the `maxminddb` package missing. After the first real visit, check that the
    log has no `forwarding headers ignored` (proxy ranges).
12. **Run the ingest once** (`python -m app.ingest.pipeline`) so the bot has the site to answer from.

## Deploy

```bash
gcloud run deploy deependhq-assistant --source . --region asia-south1 \
  --env-vars-file .env.yaml --min-instances 1 --max-instances 1 --no-cpu-throttling
```

* `--min-instances 1` and `--no-cpu-throttling` keep the in-process scheduler (recrawl, digest, reminders, alerts,
  purges) running between requests, and the rate limiter alive. `--max-instances 1` because the scheduler and rate
  limiter live in the process: a second instance would run every job twice. The image runs a single worker on purpose.
* The database is Cloud SQL (Postgres 16 + `vector`) or Neon. The image bakes in the embedding model and Node for the
  rich digest.
* A container's disk is not kept between instances, so with `mmdb` each new instance downloads the GeoLite2 files at
  startup (ipwho answers meanwhile). Point `GEOIP_MMDB_DIR` at a mounted volume to keep them, as `docker-compose.yml`
  does with its `geoip` volume.
* App Runner, ECS or any Docker host run the same image with the same env.
* Point DNS for `<assistant-host>` at the service, set `ALLOWED_ORIGINS` to the site's origins, work through the
  [go-live checklist](#go-live-checklist) and run the ingest once.

### Scheduled jobs (in-process)

Times are in `HOST_TIMEZONE`, except the re-crawl, the purges and the lookup retry, which use `RECRAWL_TZ` (both
`Asia/Kolkata` by default).

| When | Job | Only when |
|---|---|---|
| `RECRAWL_CRON` (daily 02:30) | re-crawl and re-embed deependhq.com | always |
| daily 03:10 | purge old tracking data: IPs and user agents, idle visitor rows, unreviewed organisations, old lookup cache | always |
| `GAP_CRON` (daily 03:20) | drafted answers for unanswered questions | `GAP_LOOP_ENABLED` |
| daily 03:25 | purge old conversation memory | always |
| daily 03:30 | purge Ask Deep link analytics (`TRACK_RETENTION_DAYS`) and claims (`MEMORY_RETENTION_DAYS`) | always |
| daily 03:40 | re-learn the lead score from call outcomes | `OUTCOMES_ENABLED` |
| every 10 min | retry IP lookups that are still pending or failed | always |
| every 15 min | email approved answers to the people who asked | `GAP_LOOP_ENABLED` |
| hourly :05 | "How did the call go?" to Deep after each call | `OUTCOMES_ENABLED` |
| hourly :15 | one follow-up to visitors who started a booking on Zoom but didn't confirm | `NUDGE_ENABLED` |
| hourly :30 | hot-lead alerts | `PRECALL_ENABLED` and `HOT_LEAD_ALERTS` |
| hourly :45 | booking reminders and the "Brief for tomorrow" email | `REMINDER_ENABLED` |
| `DIGEST_CRON` (Mon 09:00) | weekly digest email to Deep | `DIGEST_ENABLED` |
| weekly, Wed 04:50 | refresh the MaxMind GeoLite2 files | `MAXMIND_LICENSE_KEY` set |

At startup the app also gives a row to any session that is missing one, seeds the starter outreach rules once, and,
with a MaxMind key, downloads the GeoLite2 files in the background if they are missing or more than 6 days old.
