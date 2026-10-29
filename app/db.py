"""Postgres + pgvector access. One pool, explicit SQL, no ORM."""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator

from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

from app.config import settings
from app.embeddings import EMBED_DIM

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS pages (
    url         TEXT PRIMARY KEY,
    title       TEXT,
    source      TEXT NOT NULL,          -- 'llms-full' | 'data.js' | 'html'
    content_sha TEXT NOT NULL,
    crawled_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    url         TEXT NOT NULL REFERENCES pages(url) ON DELETE CASCADE,
    section     TEXT,
    position    INT NOT NULL,
    text        TEXT NOT NULL,
    tokens      INT NOT NULL,
    embedding   vector({EMBED_DIM}) NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{{}}'::jsonb
);
CREATE INDEX IF NOT EXISTS chunks_url_idx ON chunks(url);
-- company websites in the knowledge (app/sites.py): site = the News tenant's slug; deependhq.com's own pages keep NULL
ALTER TABLE pages ADD COLUMN IF NOT EXISTS site TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS lastmod TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS pages_site_idx ON pages(site);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

-- Operational logs required by the brief: refusals and hand-offs, plus a daily spend ledger.
CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,          -- 'refusal' | 'handoff' | 'lead' | 'booking_api' | 'injection' | 'error'
    session_id  TEXT,
    detail      JSONB NOT NULL DEFAULT '{{}}'::jsonb
);
CREATE INDEX IF NOT EXISTS events_kind_ts_idx ON events(kind, ts);

CREATE TABLE IF NOT EXISTS usage_daily (
    day         DATE PRIMARY KEY,
    usd         NUMERIC(10,4) NOT NULL DEFAULT 0,
    requests    INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS leads (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    reason      TEXT NOT NULL,
    slot_start  TIMESTAMPTZ,
    visitor_tz  TEXT,
    status      TEXT NOT NULL,          -- 'handoff' | 'booked' | 'enquiry'
    schedule_slug TEXT,
    brief_sent  BOOLEAN NOT NULL DEFAULT false
);
ALTER TABLE leads ADD COLUMN IF NOT EXISTS schedule_slug TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS session_id TEXT;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS company TEXT;             -- one-line company summary (app/enrich.py)
ALTER TABLE leads ADD COLUMN IF NOT EXISTS enrichment JSONB;         -- raw enrichment data
ALTER TABLE leads ADD COLUMN IF NOT EXISTS nudged_at TIMESTAMPTZ;    -- follow-up reminder sent (app/nudge.py)
ALTER TABLE leads ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ; -- host marked the Zoom booking confirmed

-- Company cache for lead enrichment (app/enrich.py): one row per email domain, refreshed after 30 days.
CREATE TABLE IF NOT EXISTS companies (
    domain      TEXT PRIMARY KEY,
    data        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- DNS proof of an email domain (app/enrich.py): mx | a | none | nxdomain | error. Separate from companies, so the 30-day
-- homepage cache filter never hides a DNS result. Domains only, no personal data.
CREATE TABLE IF NOT EXISTS domain_dns (domain TEXT PRIMARY KEY, status TEXT NOT NULL, checked_at TIMESTAMPTZ NOT NULL DEFAULT now());

-- In-chat bookings (app/booking/flow.py): one row per confirmed (or Zoom-pending) booking made in the widget.
CREATE TABLE IF NOT EXISTS bookings (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    lead_id         BIGINT,
    session_id      TEXT,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    company         TEXT,
    notes           TEXT,
    schedule_slug   TEXT NOT NULL,
    schedule_name   TEXT,
    duration_min    INT NOT NULL,
    start_utc       TIMESTAMPTZ NOT NULL,
    end_utc         TIMESTAMPTZ NOT NULL,
    visitor_tz      TEXT NOT NULL,
    method          TEXT NOT NULL,            -- 'scheduler' | 'meeting' | 'handoff'
    zoom_meeting_id TEXT,
    join_url        TEXT,
    passcode        TEXT,
    zoom_event_id   TEXT,
    handoff_url     TEXT,
    status          TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed | pending_zoom | cancelled
    manage_token    TEXT NOT NULL,
    cancelled_at    TIMESTAMPTZ,
    origin          TEXT,
    company_line    TEXT,
    zoom_error      TEXT
);
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS zoom_reschedule_url TEXT;   -- links read off the scheduler's confirmation page
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS zoom_cancel_url TEXT;       -- (method 'browser', app/booking/browser_booking.py)
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS zoom_run JSONB;             -- the worker's result summary
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS previous_start_utc TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS rescheduled_at TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_sent_at TIMESTAMPTZ;   -- day-before reminder (app/reminders.py)
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS schedule_description TEXT;     -- what the call type covers, for preparation help
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS attendees JSONB NOT NULL DEFAULT '[]'::jsonb;  -- extra guests: a list of name + email objects
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS brief JSONB;            -- pre-call brief for the host: lead score and talking points (app/precall.py)
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS brief_at TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS outcome TEXT;           -- good_fit | not_fit | no_show | follow_up (app/outcomes.py)
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS outcome_note TEXT;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS outcome_at TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS outcome_asked_at TIMESTAMPTZ;  -- the "how did it go?" email to the host
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS followup JSONB;         -- drafted follow-up email to the visitor: subject, body, sent_at
CREATE INDEX IF NOT EXISTS bookings_start_idx ON bookings(start_utc);
CREATE INDEX IF NOT EXISTS bookings_email_idx ON bookings(lower(email));

-- Session origin tracking (app/tracking.py): one row per chat session, geolocated from the client IP.
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    visitor_id    TEXT,                           -- persistent id from the site's localStorage (no cookie)
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip            TEXT,                           -- nulled after TRACK_RETENTION_DAYS; masked if TRACK_IP_MODE=masked
    user_agent    TEXT,
    page          TEXT,                           -- landing page the chat was opened on
    referrer      TEXT,
    referrer_host TEXT,
    channel       TEXT,                           -- direct | internal | search | social | ai | email | paid | referral
    utm           JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    client_tz     TEXT,
    lang          TEXT,
    screen        TEXT,
    country       TEXT,
    country_code  TEXT,
    region        TEXT,
    city          TEXT,
    lat           DOUBLE PRECISION,
    lon           DOUBLE PRECISION,
    isp           TEXT,
    geo_tz        TEXT,
    geo_status    TEXT,                           -- pending | ok | failed | private | disabled | unknown (row created without an IP)
    messages      INT NOT NULL DEFAULT 0,
    leads         INT NOT NULL DEFAULT 0
);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_id TEXT;      -- signed-in visitors (in-app widget)
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_name TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_email TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_read_at TIMESTAMPTZ;  -- Messages screen: unread = assistant turns after this
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title TEXT;                 -- conversation title (app/titles.py)
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title_source TEXT;          -- 'auto' | 'user'
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS title_turns INT;            -- visitor turns when the auto title was made
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS verified_email TEXT;       -- the email a verified sign-in token carried (tracking.attach_user); never an unverified hint
-- the network behind the IP (app/network.py); never an IP or a hostname
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS asn INT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS net_org TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS net_domain TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS net_kind TEXT;   -- corporate|consumer|hosting|privacy|coworking|education|government|unknown|local
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS net_flags JSONB NOT NULL DEFAULT '{{}}'::jsonb;  -- mobile, proxy, hosting, why, provider, dev
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS geo_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS sessions_first_seen_idx ON sessions(first_seen DESC);
CREATE INDEX IF NOT EXISTS sessions_visitor_idx ON sessions(visitor_id);

-- Files the visitor attaches in the composer (app/media.py). Bytes live under UPLOAD_DIR; text excerpt feeds the model.
CREATE TABLE IF NOT EXISTS uploads (
    id          TEXT PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    mime        TEXT NOT NULL,
    size        INT NOT NULL,
    path        TEXT NOT NULL,
    excerpt     TEXT
);
CREATE INDEX IF NOT EXISTS uploads_session_idx ON uploads(session_id);

-- legacy per-IP cache: no longer read or written, emptied by tracking.purge(); drop in a later release
CREATE TABLE IF NOT EXISTS ip_geo (
    ip          TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- geo + network lookups cached per /24 (IPv4) or /48 (IPv6); data never holds an IP or a hostname
CREATE TABLE IF NOT EXISTS ip_net (
    net         TEXT PRIMARY KEY,               -- tracking.mask_ip()
    provider    TEXT,
    data        JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    status      TEXT NOT NULL,                  -- ok | failed
    retry_after TIMESTAMPTZ,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ip_net_fetched_idx ON ip_net(fetched_at);

-- Conversation inbox (app/inbox.py): every turn, with the outcome of each assistant turn and visitor feedback.
CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,                  -- 'user' | 'assistant'
    text        TEXT NOT NULL,
    question    TEXT,                           -- assistant rows: the visitor message they answer
    outcome     TEXT,                           -- answered | custom | refused | injection | booking | handover | error | stopped
    reason      TEXT,                           -- refusal reason, error text
    sources     JSONB NOT NULL DEFAULT '[]'::jsonb,
    latency_ms  INT,
    model       TEXT,
    feedback    SMALLINT,                       -- 1 thumbs up, -1 thumbs down
    feedback_note TEXT,
    feedback_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS messages_session_idx ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS messages_ts_idx ON messages(ts DESC);

-- Owner-editable behaviour (app/guidance.py): free-text guidance appended to the prompt, and custom answers
-- matched by embedding similarity before retrieval runs.
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Proactive outreach (app/outreach.py): owner rules for when the greeting bubble opens and what it says, and
-- one row per firing so each rule's opens / chats / bookings can be counted.
CREATE TABLE IF NOT EXISTS outreach_rules (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    priority        INT NOT NULL DEFAULT 10,
    cooldown_hours  INT NOT NULL DEFAULT 24,
    trigger         JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    message         JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS outreach_events (
    id              BIGSERIAL PRIMARY KEY,
    fired_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    rule_id         BIGINT NOT NULL,
    visitor_id      TEXT,
    page            TEXT,
    session_id      TEXT,
    opened_at       TIMESTAMPTZ,
    dismissed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS outreach_events_rule_idx ON outreach_events(rule_id, visitor_id, fired_at DESC);
-- Returning visitors who may never chat (app/visitors.py): one row per device id, and the organisations whose
-- networks they came from. No IP, city, ASN or org column on visitors, by design.
CREATE TABLE IF NOT EXISTS visitors (
    visitor_id      TEXT PRIMARY KEY,               -- localStorage dh_vid; never linked by IP; no IP column by design
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    visits          INT NOT NULL DEFAULT 1,         -- +1 after OUTREACH_VISIT_GAP_MIN without a check
    pages           JSONB NOT NULL DEFAULT '[]'::jsonb,  -- first 30 distinct site paths (outreach.path_of: no query string)
    first_page      TEXT,                           -- first visit; a path
    referrer_host   TEXT,
    channel         TEXT,
    utm_source      TEXT,
    engaged         TEXT,                           -- NULL (never) | chatted | booked
    net_kind        TEXT,                           -- of the last network seen
    country_code    TEXT,
    company_key     TEXT,                           -- org_networks.key of the last organisation network seen (host-side only)
    company_visits  INT NOT NULL DEFAULT 0,         -- consecutive visits seen on that organisation network
    net_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS visitors_last_seen_idx ON visitors(last_seen);
CREATE INDEX IF NOT EXISTS visitors_company_idx ON visitors(company_key, last_seen DESC) WHERE company_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS org_networks (
    key             TEXT PRIMARY KEY,               -- visitors.org_identity(): a registrable domain the org owns, else 'org:' + org_key
    org             TEXT NOT NULL,                  -- display name (network.clean_org); the owner may rename it; this is the company variable
    domain          TEXT,                           -- only a domain that belongs to the organisation, never the carrier's
    net_kind        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'auto',   -- auto | candidate (needs approval) | approved | off
    industry        TEXT NOT NULL DEFAULT '',
    industry_source TEXT,                           -- homepage | owner
    line            TEXT,                           -- optional owner-written pop-up line; replaces the template
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS org_networks_status_idx ON org_networks(status, last_seen DESC);
ALTER TABLE outreach_events ADD COLUMN IF NOT EXISTS variant TEXT;    -- company | location | plain
ALTER TABLE outreach_events ADD COLUMN IF NOT EXISTS org_key TEXT;
ALTER TABLE outreach_events ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{{}}'::jsonb;  -- org, industry, kind, country, popup; never an IP, city or ASN
CREATE INDEX IF NOT EXISTS outreach_events_session_idx ON outreach_events(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS outreach_events_visitor_idx ON outreach_events(visitor_id, fired_at DESC);
CREATE TABLE IF NOT EXISTS custom_answers (
    id          BIGSERIAL PRIMARY KEY,
    question    TEXT NOT NULL,
    answer      TEXT NOT NULL,
    link        TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT true,
    hits        INT NOT NULL DEFAULT 0,
    embedding   vector({EMBED_DIM}) NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Knowledge-gap loop (app/gaps.py): questions the assistant could not answer, grouped into drafts the owner approves.
-- An approved draft becomes a custom answer; the people who asked get the answer by email (gap_followups).
CREATE TABLE IF NOT EXISTS gap_drafts (
    id               BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    question         TEXT NOT NULL,                  -- the question in plain words (becomes the custom answer's question)
    answer           TEXT NOT NULL DEFAULT '',
    link             TEXT,
    grounded         BOOLEAN NOT NULL DEFAULT false,  -- the draft rests on site content; false = it needs the owner's facts
    missing          TEXT,                            -- what the drafter could not find on the site
    sources          JSONB NOT NULL DEFAULT '[]'::jsonb,
    status           TEXT NOT NULL DEFAULT 'draft',  -- draft | approved | dismissed
    composer         TEXT,                            -- model | rules
    note             TEXT,
    custom_answer_ids JSONB NOT NULL DEFAULT '[]'::jsonb,  -- the custom answers it became: the question and how visitors worded it
    approved_at      TIMESTAMPTZ,
    embedding        vector({EMBED_DIM}) NOT NULL
);
CREATE INDEX IF NOT EXISTS gap_drafts_status_idx ON gap_drafts(status, updated_at DESC);
CREATE TABLE IF NOT EXISTS gap_asks (
    message_id  BIGINT PRIMARY KEY,                  -- the assistant turn that could not answer (messages.id)
    draft_id    BIGINT NOT NULL,
    session_id  TEXT,
    ts          TIMESTAMPTZ NOT NULL,
    question    TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'refused'      -- refused | thumbs_down
);
CREATE INDEX IF NOT EXISTS gap_asks_draft_idx ON gap_asks(draft_id);
CREATE TABLE IF NOT EXISTS gap_followups (
    id          BIGSERIAL PRIMARY KEY,
    draft_id    BIGINT NOT NULL,
    email       TEXT NOT NULL,
    name        TEXT,
    session_id  TEXT,
    asked_at    TIMESTAMPTZ,
    question    TEXT,                                -- their own words
    status      TEXT NOT NULL DEFAULT 'pending',     -- pending | sent | skipped
    reason      TEXT,
    due_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at     TIMESTAMPTZ,
    UNIQUE (draft_id, email)
);
CREATE TABLE IF NOT EXISTS email_optouts (
    email  TEXT PRIMARY KEY,
    ts     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Working memory per conversation (app/session_memory.py). No FK to sessions: form-only sessions have no sessions row.
-- Booking and hand-over state is never stored here; it is read live from bookings and leads.
CREATE TABLE IF NOT EXISTS session_memory (
    session_id   TEXT PRIMARY KEY,
    facts        JSONB NOT NULL DEFAULT '{{}}'::jsonb,   -- field: v, src, turn, ts, prev; plus the asked and declined lists
    gist         TEXT NOT NULL DEFAULT '',
    rules_msg_id BIGINT NOT NULL DEFAULT 0,              -- last messages.id the rules saw
    model_msg_id BIGINT NOT NULL DEFAULT 0,              -- last messages.id sent to the extraction model
    model_fail   INT NOT NULL DEFAULT 0,
    extractor    TEXT,                                   -- rules | model
    forgotten_at TIMESTAMPTZ,                            -- tombstone: Clear memory in the console
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS session_memory_updated_idx ON session_memory(updated_at);

-- Ask Deep from a booking email (app/email_ask.py): a conversation opened from an email link. Never the token or the address.
CREATE TABLE IF NOT EXISTS email_ask_claims (
    id             BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    token_id       TEXT NOT NULL,                       -- sha256(token)[:32]
    booking_id     BIGINT,
    lead_id        BIGINT,                              -- the unconfirmed-hold reminder has no booking row
    role           TEXT NOT NULL,                       -- booker | guest
    kind           TEXT NOT NULL,                       -- the email it came from (email_ask.KINDS)
    email_hash     TEXT NOT NULL,                       -- links.sign('ask_deep_email', address)
    session_id     TEXT NOT NULL,
    visitor_id     TEXT,
    grant_vid      BOOLEAN NOT NULL DEFAULT false,      -- booker actions from this device, not only this session
    bind_history   BOOLEAN NOT NULL DEFAULT false,      -- this device's memory reads the anchors below
    anchor_vids    TEXT[] NOT NULL DEFAULT '{{}}',
    anchor_sids    TEXT[] NOT NULL DEFAULT '{{}}',
    expires_at     TIMESTAMPTZ NOT NULL,
    chip_q         TEXT,
    chip_sent_at   TIMESTAMPTZ,                         -- the tapped question was sent (once per token and question)
    first_typed_at TIMESTAMPTZ,                         -- a person typed a message here
    revoked_at     TIMESTAMPTZ,
    UNIQUE (token_id, session_id)
);
CREATE INDEX IF NOT EXISTS email_ask_claims_session_idx ON email_ask_claims(session_id);
CREATE INDEX IF NOT EXISTS email_ask_claims_visitor_idx ON email_ask_claims(visitor_id);
CREATE INDEX IF NOT EXISTS email_ask_claims_booking_idx ON email_ask_claims(booking_id);
CREATE INDEX IF NOT EXISTS email_ask_claims_email_idx ON email_ask_claims(email_hash);
CREATE TABLE IF NOT EXISTS email_ask_events (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    action      TEXT NOT NULL,                          -- open | chip | typed | expired | invalid
    kind        TEXT,
    booking_id  BIGINT,
    lead_id     BIGINT,
    role        TEXT,
    q           TEXT,
    target      TEXT,
    session_id  TEXT
);
CREATE INDEX IF NOT EXISTS email_ask_events_ts_idx ON email_ask_events(ts);

-- Conversations like Fin (docs/ROADMAP.md step 2): the visitor's 1-5 rating of a whole conversation, the team's
-- replies inside the thread (messages.role 'agent'), and where a hand-off stands.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS rating SMALLINT;           -- 1..5
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS rating_note TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS rated_at TIMESTAMPTZ;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS team_status TEXT;          -- NULL (AI only) | waiting | replied | closed
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS team_status_at TIMESTAMPTZ;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS team_notified_at TIMESTAMPTZ;  -- last "visitor wrote again" email to the host
ALTER TABLE messages ADD COLUMN IF NOT EXISTS author TEXT;               -- role 'agent': who on the team wrote it
ALTER TABLE messages ADD COLUMN IF NOT EXISTS notified_at TIMESTAMPTZ;   -- role 'agent': emailed to the visitor

-- Help center (app/help.py, docs/ROADMAP.md step 3): collections of articles shown in the widget's Help tab and Home
-- search. source: 'site' (made from a deependhq.com page, which retrieval already indexes), 'builtin' (written for the
-- assistant: booking, privacy...) or 'owner' (written in the console). builtin and owner articles feed the answers.
CREATE TABLE IF NOT EXISTS help_collections (
    id          BIGSERIAL PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    position    INT NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS help_articles (
    id            BIGSERIAL PRIMARY KEY,
    collection_id BIGINT REFERENCES help_collections(id) ON DELETE SET NULL,
    slug          TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL DEFAULT '',
    author        TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'owner',
    source_url    TEXT,
    published     BOOLEAN NOT NULL DEFAULT true,
    featured      BOOLEAN NOT NULL DEFAULT false,
    position      INT NOT NULL DEFAULT 0,
    views         INT NOT NULL DEFAULT 0,
    embedding     vector({EMBED_DIM}),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS help_articles_collection_idx ON help_articles(collection_id, position);
ALTER TABLE help_articles ADD COLUMN IF NOT EXISTS embedding vector({EMBED_DIM});  -- re-added after a model change

-- Saved email queue (app/mailer.py): every email is stored before it is sent, so a restart cannot lose it
CREATE TABLE IF NOT EXISTS outbox (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT NOT NULL,
    to_addr     TEXT NOT NULL,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    html        TEXT,
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    reply_to    TEXT,
    ref         TEXT,
    status      TEXT NOT NULL DEFAULT 'queued',   -- queued | sending | sent | failed
    attempts    INT NOT NULL DEFAULT 0,
    recovered   INT NOT NULL DEFAULT 0,          -- times a later process picked it up again
    last_error  TEXT,
    sent_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS outbox_status_idx ON outbox(status, updated_at);

-- News (app/news.py): per-tenant sources, the items shown in the widget's News tab, and the sitemap state diffed each run
CREATE TABLE IF NOT EXISTS news_tenants (
    slug               TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    blog_feed_url      TEXT,
    youtube_channel_id TEXT,
    mention_query      TEXT,
    sitemap_index_url  TEXT,
    sitemap_types      TEXT[] NOT NULL DEFAULT '{{}}',
    enabled            BOOLEAN NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS news_items (
    id           BIGSERIAL PRIMARY KEY,
    tenant       TEXT NOT NULL REFERENCES news_tenants(slug) ON DELETE CASCADE,
    source       TEXT NOT NULL,                  -- blog | sitemap | youtube | bing | manual
    kind         TEXT NOT NULL,                  -- post | video | mention | news | case_studies | webinar | announcement | ...
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    blurb        TEXT NOT NULL DEFAULT '',
    image        TEXT,
    status       TEXT NOT NULL DEFAULT 'published',   -- published | pending | rejected | hidden
    pinned       BOOLEAN NOT NULL DEFAULT false,
    lastmod      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant, url)
);
CREATE INDEX IF NOT EXISTS news_items_feed_idx ON news_items(tenant, status, pinned DESC, published_at DESC);
-- the item read inside the messenger (like Intercom News): its article as safe HTML, labels, who shared it, views
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS body TEXT;                       -- NULL: not read yet; '': nothing to show
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS labels TEXT[] NOT NULL DEFAULT '{{}}';
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS author TEXT;
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS views INT NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS news_reactions (                                      -- "How would you rate this?" one per visitor
    item_id    BIGINT NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
    visitor    TEXT NOT NULL,
    emoji      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, visitor)
);
ALTER TABLE news_tenants ADD COLUMN IF NOT EXISTS site_url TEXT;                         -- the website (else from the feeds)
ALTER TABLE news_tenants ADD COLUMN IF NOT EXISTS kb_enabled BOOLEAN NOT NULL DEFAULT true;  -- the assistant answers from it
CREATE TABLE IF NOT EXISTS news_sitemap_seen (
    tenant  TEXT NOT NULL,
    url     TEXT NOT NULL,
    kind    TEXT NOT NULL,
    lastmod TIMESTAMPTZ,
    PRIMARY KEY (tenant, url)
);
-- dynamic checking (NEWS_DYNAMIC): when each source is due again (sooner after a change, later while quiet) ...
CREATE TABLE IF NOT EXISTS news_sources (
    tenant        TEXT NOT NULL,
    source        TEXT NOT NULL,                 -- blog | sitemap | youtube | mention | links
    every_minutes INT NOT NULL,
    next_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    checked_at    TIMESTAMPTZ,
    changed_at    TIMESTAMPTZ,
    last_new      INT NOT NULL DEFAULT 0,
    errors        INT NOT NULL DEFAULT 0,        -- failed checks in a row
    last_error    TEXT,
    PRIMARY KEY (tenant, source)
);
-- ... and what each feed URL answered last time, so an unchanged feed costs one 304 (or one hash compare)
CREATE TABLE IF NOT EXISTS news_fetch_cache (
    tenant        TEXT NOT NULL,
    url           TEXT NOT NULL,
    etag          TEXT,
    last_modified TEXT,
    body_hash     TEXT,
    checked_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant, url)
);
"""

_pool: ConnectionPool | None = None


def _ensure_vector_extension() -> None:
    """register_vector() fails on a database without the extension, which would make every pooled
    connection fail before the schema could ever be created. Create it on a plain connection first."""
    import psycopg

    with psycopg.connect(settings.database_url, connect_timeout=10) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.commit()


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _ensure_vector_extension()
        _pool = ConnectionPool(settings.database_url, min_size=1, max_size=8, configure=register_vector,
                               open=True, timeout=15)
    return _pool


@contextmanager
def conn() -> Iterator[Any]:
    with pool().connection() as c:
        yield c


def init_schema() -> None:
    with conn() as c:
        c.execute(SCHEMA)
        # If the embedding model (and so the vector size) changed, the old chunks are useless: drop them and
        # clear the page hashes so the next ingest re-embeds everything.
        row = c.execute(
            """SELECT atttypmod FROM pg_attribute
               WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"""
        ).fetchone()
        if row and row[0] not in (-1, EMBED_DIM):
            c.execute("DROP TABLE chunks")
            c.execute("DROP TABLE IF EXISTS custom_answers")
            c.execute("DROP TABLE IF EXISTS gap_drafts")
            c.execute("DROP TABLE IF EXISTS gap_asks")
            c.execute("DELETE FROM pages")
            # help articles are written by people: keep them, only their vectors go (app/help.py re-embeds at start-up)
            c.execute("ALTER TABLE IF EXISTS help_articles DROP COLUMN IF EXISTS embedding")
            c.execute(SCHEMA)
        c.commit()


def log_event(kind: str, session_id: str | None, detail: dict[str, Any]) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO events(kind, session_id, detail) VALUES (%s, %s, %s::jsonb)",
            (kind, session_id, json.dumps(detail, default=str)),
        )
        c.commit()


def get_setting(key: str) -> str | None:
    with conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    return row[0] if row else None


def get_settings_prefix(prefix: str) -> dict[str, str]:
    with conn() as c:
        rows = c.execute("SELECT key, value FROM settings WHERE key LIKE %s", (prefix + "%",)).fetchall()
    return {k[len(prefix):]: v for k, v in rows}


def set_setting(key: str, value: str | None) -> None:
    """None deletes the row (so the code default applies again)."""
    with conn() as c:
        if value is None:
            c.execute("DELETE FROM settings WHERE key = %s", (key,))
        else:
            c.execute("""INSERT INTO settings(key, value, updated_at) VALUES (%s, %s, now())
                         ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""", (key, value))
        c.commit()


def add_spend(usd: float) -> float:
    """Add to today's ledger and return the new daily total (UTC day)."""
    with conn() as c:
        row = c.execute(
            """
            INSERT INTO usage_daily(day, usd, requests) VALUES (%s, %s, 1)
            ON CONFLICT (day) DO UPDATE SET usd = usage_daily.usd + EXCLUDED.usd,
                                            requests = usage_daily.requests + 1
            RETURNING usd
            """,
            (date.today(), usd),
        ).fetchone()
        c.commit()
        return float(row[0])


def spend_today() -> float:
    with conn() as c:
        row = c.execute("SELECT usd FROM usage_daily WHERE day = %s", (date.today(),)).fetchone()
        return float(row[0]) if row else 0.0
