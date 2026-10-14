# Session origin tracking

Every chat session is recorded with where it came from. This answers "who is talking to the bot, from where,
and what brought them here", and it puts a one-line origin into the host brief for each lead.

## What is collected, and when

| When | What | Where it goes |
|---|---|---|
| Chat opened (the `/track` beacon) | session id, visitor id, landing page URL, referrer, UTM parameters, browser timezone, language, screen size, user agent, **client IP** | `sessions` row |
| A few hundred ms later (background thread) | country, region, city, lat/lon, ISP, timezone, and the network behind the IP (AS number, owner, domain, kind), derived from the IP | same row, `geo_*` and `net_*` columns |
| Every chat message | `last_seen`, `messages` counter, visitor id (creates the row if the beacon never fired) | same row |
| Booking confirm, hand-over, reschedule, cancel | creates the row if missing: visitor id, IP (then geo), user agent | same row |
| A lead is saved | `leads.session_id`, `sessions.leads += 1` (creating the row if needed), origin line in the host brief email | `leads` row, email |
| Every 10 minutes | lookups still `pending` or `failed` from the last 2 days are retried (`retry_pending`) | same row |
| Page views without a chat (`/outreach/check`, docs/OUTREACH.md) | device id, first page path, referrer host, channel, utm_source, up to 30 distinct site paths, a server visit count, chatted/booked, and the kind, country and organisation key of the current network. **Never the IP, city or ASN** | `visitors` row (one per device id), `org_networks` |
| Daily 03:10 host time (and at startup) | IP and user agent nulled on rows older than `TRACK_RETENTION_DAYS`, and city/region/coordinates too unless the network is a company, university, government or cloud one (keep-list below); `ip_net` rows older than 30 days and the legacy `ip_geo` table dropped; orphan sessions backfilled; `visitors` rows idle longer than `TRACK_RETENTION_DAYS` and unreviewed `org_networks` rows deleted; older `outreach_events` lose their visitor id and context | purge |

**One write path.** Every writer goes through `tracking.ensure_session()`, one upsert where the first value wins
for the visitor id, page, referrer, UTM and timezone. An IP only fills a row that never had one, so a row purged
after its geo lookup is never re-geolocated from a later request. The widget counts a session as tracked only when
`/track` answered `ok`; until then `/chat` and `/booking/confirm` carry the same fields in a `beacon` object, which
covers a lost or blocked beacon. `inbox.log_message` also inserts a bare row (`geo_status=unknown`) as a last
resort, and `backfill_orphans()` (in `purge`, result `orphans_backfilled`) repairs any session that has messages,
bookings or leads but no row; a non-zero count there means a write path skipped `ensure_session`. The host booking
email re-reads the origin line just before it is sent, so it shows the finished geo instead of "location pending".

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
* **Network line:** the pre-call brief carries `Network:  Reliance Jio · home broadband` (or
  `Infosys · company network · matches their email domain`); the `Where:` line itself is unchanged.
* **Quick lookup from the shell:** `python -m app.tracking 49.207.200.10 'Apple.INC' a@gmail.com` prints the
  normalised lookup, `classify()` and `match()` with no database. This is the main local test path.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TRACKING_ENABLED` | `true` | `false` turns the beacon into a no-op; session rows then hold only the visitor id and the message/lead counters (`geo_status=disabled`), never IP, user agent, page, referrer, timezone, language or screen |
| `GEOIP_PROVIDER` | `ipwho` | `ipwho` (ipwho.is, free, no key, HTTPS, ~10k/month), `ipinfo` (token, 50k/month, commercial OK), `ipapi` (ip-api.com, HTTP only, non-commercial; startup warns), `ipapiis` (api.ipapi.is, HTTPS, no key, ~1k/day; verify its terms before enabling), `mmdb` (local MaxMind GeoLite2 files), `none`, or a comma chain such as `mmdb,ipwho` (the first `ok` wins) |
| `GEOIP_TOKEN` | | ipinfo token |
| `GEOIP_MMDB_DIR` | | folder with `GeoLite2-City.mmdb` and `GeoLite2-ASN.mmdb`. Needs `pip install maxminddb` (not in requirements.txt), a MaxMind account and licence key, attribution, and refreshing the files within 30 days (EULA). GeoLite2-ASN has no domain, so email matching falls back to the org name. Missing package or files: skipped with one log line |
| `GEOIP_DAILY_CAP` | `300` | outbound lookups per provider per UTC day, counted in-process (the app runs one worker); over the cap the provider is skipped with reason `quota` |
| `GEOIP_FAIL_RETRY_MIN` | `60` | a failed /24 lookup is cached this long before the provider is asked again |
| `GEOIP_DEV_IP` | | local dev only: honoured only when `DATABASE_URL` points at localhost/127.0.0.1. Private IPs are looked up as this public IP instead and tagged `dev` (admin chip tooltip, `[dev test IP]` in the brief), so every local session gets the same place |
| `NET_RDNS` | `false` | reverse DNS on public IPs (background, 1 s cap). Off by default: the PTR query reaches the IP owner's DNS, and hostnames embed the IP. Only the registrable domain and a "looks dynamic" flag are kept, never the hostname |
| `NET_SCORE` | `true` | the network rules in the lead score (below) |
| `TRUSTED_PROXIES` | private ranges + loopback | peers whose forwarding headers are believed (CIDR list). The default suits nginx or docker in front of the app. If Cloudflare connects to the app directly, add Cloudflare's published IP ranges, otherwise every visitor resolves to a Cloudflare edge IP and is classed as a privacy network; an hourly `forwarding headers ignored` warning shows when this is wrong |
| `TRACK_IP_MODE` | `full` | `masked` stores only the /24 (IPv4) or /48 (IPv6) after the geo lookup |
| `TRACK_RETENTION_DAYS` | `90` | after this the IP and user agent are nulled; the geo/channel aggregate stays |
| `TRUST_PROXY` | `true` | honour forwarding headers, and only from a peer in `TRUSTED_PROXIES`. `X-Forwarded-For` is walked right to left past trusted hops, and the first untrusted hop is the visitor: it wins over `CF-Connecting-IP` and `X-Real-IP`, which are read only when every hop is a trusted proxy (Cloudflare's ranges listed) or, for `X-Real-IP`, when there is no `X-Forwarded-For`. nginx forwards a visitor's own `CF-Connecting-IP` unchanged, so behind nginx also clear it: `proxy_set_header CF-Connecting-IP "";` (and `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`). Set `false` only when the app faces the internet directly |
| `ADMIN_TOKEN` | | required for `/admin/*`; empty disables them |
| `OUTREACH_VISITORS` | `true` | a `visitors` row per browser for page views without a chat (needs `TRACKING_ENABLED`) |
| `OUTREACH_GEO_DAILY_CAP` | `150` | network lookups for page views per UTC day (in-process). They also count against `GEOIP_DAILY_CAP`, which keeps the rest for chat and booking lookups; a page view over this cap is not cached as a failure, so a later chat lookup of the same /24 still runs |
| `OUTREACH_HONOR_GPC` | `true` | with Global Privacy Control or Do Not Track: no `visitors` row, no lookup, no IP context |
| `OUTREACH_NO_PERSONALISE_COUNTRIES` | EEA + GB + CH | no IP context for these countries; while the list is non-empty a browser timezone under `Europe/` skips the `visitors` row and the lookup entirely, before any processing. Clear it only with a consent banner |

Results are cached per /24 (IPv4) or /48 (IPv6) in `ip_net` for 30 days (failures for `GEOIP_FAIL_RETRY_MIN`), so the
provider sees each network once. The cache key is the masked network and the cached data never holds an IP or a
hostname. Private and loopback addresses are never sent to the provider (`geo_status=private`, network
`local test network`), which is what local testing shows; use `GEOIP_DEV_IP` or the CLI to see the rest. A 429 pauses a
provider (Retry-After or ip-api's X-Ttl, else 15 min), and so do 5 errors in a row. The legacy per-IP `ip_geo` table
is no longer read or written; purge empties it.

## The network behind the IP

`app/network.py` (pure, unit-tested) turns the lookup into columns on `sessions`: `asn`, `net_org` (the AS owner, or
the netblock holder for a company sub-allocation), `net_domain`, `net_kind` and `net_flags` (`mobile`, `proxy`,
`hosting`, `why`, `provider`, `dev`; never an IP or hostname), plus `geo_at`. A failed lookup leaves `net_kind` empty
until the retry job succeeds.

`net_kind` is one of `corporate`, `consumer` (home or mobile broadband; `mobile` is a flag), `hosting` (cloud server),
`privacy` (VPN, relay or security gateway: iCloud Private Relay, Cloudflare WARP, Zscaler, Netskope), `coworking`,
`education`, `government`, `unknown`, `local`. The classifier runs in this order and the first rule wins:

1. private address: `local`
2. a provider flag proxy/VPN/Tor: `privacy`
3. a provider type (ipapi.is, ipinfo paid plans): business, isp, hosting, education, government; then a provider
   hosting flag (`hosting`) or mobile flag (`consumer`, mobile)
4. a netblock registered to another organisation than the AS owner, whose name is not an ISP, host, VPN, cowork,
   university or government name (ip-api `org`, ipapi.is `company`): `corporate`
5. the curated `KNOWN_ASN` list (Amazon, Google, Microsoft ... hosting; Cloudflare, Akamai relay, Fastly, Zscaler,
   Netskope ... privacy; Jio, Airtel, BSNL, ACT, Hathway, Comcast ... consumer). Tata Communications (AS4755) and
   Verizon Business (AS701) are deliberately absent: they carry enterprise lines. Add an ASN when a real lookup lands
   in the wrong kind.
6. name rules over the AS owner, org, ISP and domain, in the order privacy, hosting, coworking, education,
   government, consumer (deliberately no bare "networks", "communications" or "internet": Palo Alto Networks is a
   buyer, not broadband)
7. with `NET_RDNS`: a static reverse-DNS name on another company's domain: `corporate`
8. otherwise `unknown`; the type is never guessed

The network is then checked against what the visitor told us (`network.match`): `claim` (it belongs to the company
they typed; only on corporate, unknown, education or government networks, so "Reliance" typed on Jio proves nothing),
`email` (it belongs to their business email domain), `mismatch`, `other_company`, or just the kind.

**Lead score** (`NET_SCORE`): +10 when the network matches the typed company and the email is not a business one,
+5 when it matches their business email domain (corroboration; a checked email domain already earned +15), +3 for an unrelated
company network with no typed company and a personal email. Mismatch, home/mobile, VPN/relay/cloud/cowork and
university/government networks are noted at 0 points: big-company staff often browse through security proxies or
Private Relay, so the network never costs points. The brief facts also carry a "Company check" line when a typed
company is backed by neither the email nor the network, and a note when the browser timezone and the IP location are
2+ hours apart. Network org and kind are host-only: they never reach the visitor-facing prompt, with one scoped
exception (below).

## Returning visitors without a chat (app/visitors.py)

`/outreach/check` (the greeting loader, docs/OUTREACH.md) keeps one `visitors` row per device id (`dh_vid`): first
page path, referrer host, channel, utm_source, up to 30 distinct site paths (no query string), a visit count kept on
the server (a new visit after `OUTREACH_VISIT_GAP_MIN` minutes without a check), whether the device chatted or booked,
and the kind, country code and organisation key of the last network seen. **No IP, city or ASN is stored for
visitors**, and an IP never links rows: it only looks up the network through the `ip_net` /24 cache (read-only on the
request; a miss is looked up in the background, capped by `OUTREACH_GEO_DAILY_CAP`). `org_networks` holds one row per
organisation network seen (display name, its own domain, kind, the owner's status, industry and pop-up line). Pages of
the assistant's own host (`/demo`, `/site`) are not recorded unless the database is local.

Nothing is recorded for bots, for browsers sending Global Privacy Control or DNT (`OUTREACH_HONOR_GPC`), and, while
`OUTREACH_NO_PERSONALISE_COUNTRIES` is non-empty (default: the EEA plus GB and CH), for browsers whose timezone is under
`Europe/`. A cached lookup in one of those countries also gives no context.

Retention: `visitors` rows idle for `TRACK_RETENTION_DAYS` and unreviewed `org_networks` rows not seen for as long are
deleted; `outreach_events` older than that lose their visitor id and context. `DELETE /admin/visitors/{visitor_id}`
and the console's "forget this visitor" (memory, `?visitor=1`) delete the device's row and scrub its events.

**The scoped exception to "network is host-only".** A returning visitor who never chatted may see a pop-up that names
the organisation of their current network ("Exploring B2B data for Acme?") or its country. Only if they tap it does
the chat get that name, an industry guess and the pop-up text, in a user-role DATA message labelled as an automatic
guess (`app/outreach.data_block`). The city, ASN, network kind and IP never reach the visitor or the model, and nothing
remembered from another network is ever shown (`app/memory.py` docstring). The pre-call brief notes when a typed
company merely echoes such a pop-up (`network_company_prompted`, 0 points).

**Purge keep-list:** after `TRACK_RETENTION_DAYS`, city, region and coordinates survive only for `corporate`,
`education`, `government` and `hosting` networks; `consumer` and `unknown` (mostly residential) lose them. Country and
`net_org` stay.

## Privacy obligations this creates

The site's footer and `/privacy` currently promise "no cookies, no trackers". This feature keeps "no cookies" true
and makes "no trackers" false. Before go-live:

1. Change the footer disclosure (see `docs/WIDGET_SWAP.md`) to: "the Ask Deep chat stores your messages, your IP
   address and approximate location, and the page you came from, to improve answers and to follow up on booking
   requests".
2. Add the same to `/privacy`, with the retention period (`TRACK_RETENTION_DAYS`) and every provider in the
   `GEOIP_PROVIDER` chain named as a processor. Suggested wording: "approximate location and the network/organisation
   your connection belongs to, looked up via <named providers>; used to prepare the host for a call (this summary may
   be processed by our AI model provider)". The network organisation reaches the LLM provider through the brief.
3. Use `TRACK_IP_MODE=masked` (recommended, now that nothing reads the full IP after the lookup): it keeps city-level
   geo while storing no full IP. Keep retention short. Under GDPR an IP address is personal data; a masked one is much
   easier to justify on legitimate interest.
4. `/admin` must sit behind HTTPS and a strong `ADMIN_TOKEN`; it exposes IPs.
5. Page views without a chat (above) need their own line in the privacy notice before go-live. Suggested wording:
   "When you browse deependhq.com, the site assistant notes which of its pages you open on this browser and looks up
   the organisation and country your internet connection belongs to (via <named providers>; the IP address itself is
   not kept for this) so it can offer relevant help on a later visit. If you open the chat from such a suggestion, our
   AI provider sees that guess. Global Privacy Control is honoured." Clearing `OUTREACH_NO_PERSONALISE_COUNTRIES`
   without a consent banner is a legal decision, not a technical one.

## Verifying it locally

`pytest tests/test_tracking.py tests/test_network.py` covers the beacon, the origin line, the lookup cache, the
classifier and the admin summary. By hand: open
`http://localhost:8080/site?utm_source=test`, send two messages, then open Console → Conversations; the session shows its
channel, campaign and (behind a proxy with `TRUST_PROXY=true`) the visitor's city.
