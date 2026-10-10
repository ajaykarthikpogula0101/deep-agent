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
    geo_status    TEXT,                           -- pending | ok | failed | private | disabled
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

CREATE TABLE IF NOT EXISTS ip_geo (
    ip          TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
            c.execute("DELETE FROM pages")
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
