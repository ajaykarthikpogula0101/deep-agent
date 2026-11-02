"""Central settings. Every secret comes from the environment; nothing is hardcoded."""
from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM: any OpenAI-compatible chat endpoint (OpenAI, Groq, Together, OpenRouter, HF Inference Providers)
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")  # legacy fallback for LLM_API_KEY
    llm_base_url: str = Field(default="", alias="LLM_BASE_URL")  # empty = api.openai.com
    chat_model: str = Field(default="openai/gpt-oss-120b", alias="CHAT_MODEL")
    # an answer never waits longer than this for the model (seconds; also the longest gap between streamed tokens)
    chat_timeout: float = Field(default=30, alias="CHAT_TIMEOUT")
    # backup model when the main one fails before answering (dead key, outage, timeout); empty = none. The key and base
    # URL default to the main ones, so another provider (e.g. Groq) needs CHAT_FALLBACK_API_KEY and _BASE_URL too
    chat_fallback_model: str = Field(default="", alias="CHAT_FALLBACK_MODEL")
    chat_fallback_api_key: str = Field(default="", alias="CHAT_FALLBACK_API_KEY")
    chat_fallback_base_url: str = Field(default="", alias="CHAT_FALLBACK_BASE_URL")
    # health checks (app/health.py): every HEALTH_CRON, alerts to ALERT_EMAIL (empty = HOST_EMAIL)
    health_checks: bool = Field(default=True, alias="HEALTH_CHECKS")
    health_cron: str = Field(default="*/10 * * * *", alias="HEALTH_CRON")
    alert_email: str = Field(default="", alias="ALERT_EMAIL")
    credit_alert_usd: float = Field(default=2.0, alias="CREDIT_ALERT_USD")   # warn when the model key has less left than this
    # help center (app/help.py): Help tab, Home search card, and owner/builtin articles as answer sources
    help_enabled: bool = Field(default=True, alias="HELP_ENABLED")
    help_search_min_score: float = Field(default=0.6, alias="HELP_SEARCH_MIN_SCORE")
    help_answer_min_score: float = Field(default=0.62, alias="HELP_ANSWER_MIN_SCORE")  # cite an article in a chat answer
    # the team answering inside the chat (app/team.py)
    team_reply_author: str = Field(default="Deep", alias="TEAM_REPLY_AUTHOR")            # name shown on console replies
    team_email_after_minutes: int = Field(default=3, alias="TEAM_EMAIL_AFTER_MINUTES")  # unread team reply -> email
    team_host_notify_minutes: int = Field(default=15, alias="TEAM_HOST_NOTIFY_MINUTES")  # "visitor wrote again" throttle
    # News tab (app/news.py): which tenant this widget shows, and how far back / how many items
    news_enabled: bool = Field(default=True, alias="NEWS_ENABLED")
    news_tenant: str = Field(default="lakeb2b", alias="NEWS_TENANT")
    news_days: int = Field(default=30, alias="NEWS_DAYS")
    news_limit: int = Field(default=20, alias="NEWS_LIMIT")
    # dynamic checking: one job every NEWS_TICK_MINUTES checks the sources that are due (off: fixed hourly / daily runs)
    news_dynamic: bool = Field(default=True, alias="NEWS_DYNAMIC")
    news_feed_days: int = Field(default=365, alias="NEWS_FEED_DAYS")   # how far back a feed (Newsletters, Case studies...) goes
    news_popup: bool = Field(default=True, alias="NEWS_POPUP")         # a new item pops up above the closed launcher, once
    news_tick_minutes: int = Field(default=5, alias="NEWS_TICK_MINUTES")
    # company websites in the assistant's knowledge (app/sites.py): the News tenants' sites, indexed and searched live
    kb_sites_enabled: bool = Field(default=True, alias="KB_SITES_ENABLED")
    kb_sites_every_hours: int = Field(default=6, alias="KB_SITES_EVERY_HOURS")
    kb_site_pages_per_run: int = Field(default=1000, alias="KB_SITE_PAGES_PER_RUN")
    kb_site_max_pages: int = Field(default=5000, alias="KB_SITE_MAX_PAGES")
    kb_live_search: bool = Field(default=True, alias="KB_LIVE_SEARCH")
    # every email saved before sending, re-sent after a restart (app/mailer.py)
    mail_outbox: bool = Field(default=True, alias="MAIL_OUTBOX")
    # only one process runs the scheduled jobs (app/leader.py); false = every process runs them (the old behaviour)
    scheduler_lock: bool = Field(default=True, alias="SCHEDULER_LOCK")
    # nightly database backups outside Docker (app/backup.py); relative BACKUP_DIR = inside the project
    backup_enabled: bool = Field(default=True, alias="BACKUP_ENABLED")
    backup_dir: str = Field(default="backups", alias="BACKUP_DIR")
    backup_keep: int = Field(default=14, alias="BACKUP_KEEP")
    backup_cron: str = Field(default="50 3 * * *", alias="BACKUP_CRON")
    backup_docker_container: str = Field(default="deependhq-assistant-db-1", alias="BACKUP_DOCKER_CONTAINER")
    backup_timeout: int = Field(default=600, alias="BACKUP_TIMEOUT")
    # Embeddings: "local" = Hugging Face model via fastembed (free, no key, ~130 MB download, CPU);
    # "api" = an OpenAI-compatible /embeddings endpoint (remote, server-side; EMBED_API_KEY/EMBED_BASE_URL default
    # to the LLM ones). Changing provider or model changes the vector size: re-run the ingest afterwards.
    embed_provider: str = Field(default="local", alias="EMBED_PROVIDER")
    embed_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBED_MODEL")
    embed_api_key: str = Field(default="", alias="EMBED_API_KEY")
    embed_base_url: str = Field(default="", alias="EMBED_BASE_URL")
    embed_dim: int = Field(default=0, alias="EMBED_DIM")  # 0 = look the model up; set it for an unknown API model

    # DB
    database_url: str = Field(default="postgresql://assistant:assistant@127.0.0.1:5432/assistant", alias="DATABASE_URL")

    # KB
    site_base_url: str = Field(default="https://deependhq.com", alias="SITE_BASE_URL")
    crawl_user_agent: str = Field(
        default="deependhq-assistant/0.1 (+https://deependhq.com; answers questions about this site)",
        alias="CRAWL_USER_AGENT",
    )
    recrawl_cron: str = Field(default="30 2 * * *", alias="RECRAWL_CRON")
    recrawl_tz: str = Field(default="Asia/Kolkata", alias="RECRAWL_TZ")
    retrieval_min_score: float = Field(default=0.60, alias="RETRIEVAL_MIN_SCORE")  # bge-small scale, between on- and off-topic scores
    retrieval_top_k: int = Field(default=6, alias="RETRIEVAL_TOP_K")
    # between this and RETRIEVAL_MIN_SCORE the model still sees the (loosely related) sources and may answer from them
    # or say it could not find it; below it the fixed "couldn't find that" reply goes out without a model call
    retrieval_soft_floor: float = Field(default=0.50, alias="RETRIEVAL_SOFT_FLOOR")
    custom_answer_min_score: float = Field(default=0.86, alias="CUSTOM_ANSWER_MIN_SCORE")  # owner-written answers fire above this

    # Security / cost
    allowed_origins: str = Field(default="https://deependhq.com,https://www.deependhq.com", alias="ALLOWED_ORIGINS")
    rate_limit_per_minute: int = Field(default=20, alias="RATE_LIMIT_PER_MINUTE")
    rate_limit_per_day: int = Field(default=200, alias="RATE_LIMIT_PER_DAY")
    daily_spend_cap_usd: float = Field(default=5.0, alias="DAILY_SPEND_CAP_USD")
    max_message_chars: int = Field(default=1500, alias="MAX_MESSAGE_CHARS")
    admin_token: str = Field(default="", alias="ADMIN_TOKEN")  # empty = admin endpoints disabled
    # Signed-in visitors (the in-app widget): either an HMAC token minted by the host app's backend with this secret,
    # or a Clerk session JWT verified against the issuer's JWKS. Empty = anonymous visitors only.
    widget_signing_secret: str = Field(default="", alias="WIDGET_SIGNING_SECRET")
    clerk_jwt_issuer_domain: str = Field(default="", alias="CLERK_JWT_ISSUER_DOMAIN")
    widget_demo: bool = Field(default=True, alias="WIDGET_DEMO")  # /demo page with a sample signed-in user; off in prod
    privacy_url: str = Field(default="https://deependhq.com/privacy", alias="PRIVACY_URL")

    # Composer media (docs/WIDGET.md §6)
    upload_dir: str = Field(default="uploads", alias="UPLOAD_DIR")
    upload_max_mb: float = Field(default=10, alias="UPLOAD_MAX_MB")
    gif_provider: str = Field(default="tenor", alias="GIF_PROVIDER")  # tenor | giphy
    gif_api_key: str = Field(default="", alias="GIF_API_KEY")  # empty = GIF button hidden
    # speech-to-text: "browser" = Web Speech API in the widget; "openai" = any OpenAI-compatible /audio/transcriptions
    # (Groq whisper-large-v3, OpenAI whisper-1) used as the fallback and by the voice mode
    stt_provider: str = Field(default="browser", alias="STT_PROVIDER")  # browser | openai
    stt_api_key: str = Field(default="", alias="STT_API_KEY")
    stt_base_url: str = Field(default="https://api.groq.com/openai/v1", alias="STT_BASE_URL")
    stt_model: str = Field(default="whisper-large-v3", alias="STT_MODEL")
    # text Whisper reads as "what came before" (e.g. product names). Off by default: on the 2026-10-14 multilingual benchmark a
    # names list raised the error rate from 9.8% to 12.3% (Kannada came back translated); docs/MEMORY_VOICE.md "Accuracy"
    stt_prompt: str = Field(default="", alias="STT_PROMPT")
    stt_hint_recheck: bool = Field(default=True, alias="STT_HINT_RECHECK")  # re-read in the visitor's own language when detection disagrees
    # text-to-speech: "browser" = SpeechSynthesis in the widget; "openai" = /audio/speech (OpenAI tts-1 or compatible)
    tts_provider: str = Field(default="browser", alias="TTS_PROVIDER")  # browser | openai
    tts_api_key: str = Field(default="", alias="TTS_API_KEY")
    tts_base_url: str = Field(default="https://api.openai.com/v1", alias="TTS_BASE_URL")
    tts_model: str = Field(default="tts-1", alias="TTS_MODEL")
    tts_voice: str = Field(default="alloy", alias="TTS_VOICE")
    trust_proxy: bool = Field(default=True, alias="TRUST_PROXY")  # honour CF-Connecting-IP / X-Forwarded-For

    # Session origin tracking (app/tracking.py)
    tracking_enabled: bool = Field(default=True, alias="TRACKING_ENABLED")
    # ipwho | ipinfo | ipapi | ipapiis | mmdb | none, or a comma chain such as mmdb,ipwho
    geoip_provider: str = Field(default="ipwho", alias="GEOIP_PROVIDER")
    geoip_token: str = Field(default="", alias="GEOIP_TOKEN")  # ipinfo only
    geoip_mmdb_dir: str = Field(default="", alias="GEOIP_MMDB_DIR")  # GeoLite2-City.mmdb + GeoLite2-ASN.mmdb; empty = data/geoip with a MaxMind key
    # MaxMind GeoLite2 downloads (app/geoip_update.py): the licence key alone works on the legacy URL; with the account id
    # the current basic-auth endpoint is used. Empty key = nothing is downloaded
    maxmind_account_id: str = Field(default="", alias="MAXMIND_ACCOUNT_ID")
    maxmind_license_key: str = Field(default="", alias="MAXMIND_LICENSE_KEY")
    geoip_daily_cap: int = Field(default=300, alias="GEOIP_DAILY_CAP")  # per provider per UTC day, in-process
    geoip_fail_retry_min: int = Field(default=60, alias="GEOIP_FAIL_RETRY_MIN")  # a failed /24 is not looked up again before this
    geoip_dev_ip: str = Field(default="", alias="GEOIP_DEV_IP")  # honoured only with a localhost DATABASE_URL
    # peers whose forwarding headers are believed; add Cloudflare's ranges if Cloudflare connects to the app directly
    trusted_proxies: str = Field(default="127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7",
                                 alias="TRUSTED_PROXIES")
    net_rdns: bool = Field(default=False, alias="NET_RDNS")  # reverse DNS on public IPs (background, 1 s cap)
    net_score: bool = Field(default=True, alias="NET_SCORE")  # the network rules in the lead score
    track_ip_mode: str = Field(default="full", alias="TRACK_IP_MODE")  # full | masked (/24, /48)
    track_retention_days: int = Field(default=90, alias="TRACK_RETENTION_DAYS")

    # Automations (docs/AUTOMATIONS.md): weekly digest, follow-up nudges, lead enrichment, smart suggestions, languages
    digest_enabled: bool = Field(default=True, alias="DIGEST_ENABLED")
    digest_cron: str = Field(default="0 9 * * 1", alias="DIGEST_CRON")  # Monday 09:00, host timezone
    nudge_enabled: bool = Field(default=True, alias="NUDGE_ENABLED")
    nudge_after_hours: int = Field(default=24, alias="NUDGE_AFTER_HOURS")
    reminder_enabled: bool = Field(default=True, alias="REMINDER_ENABLED")  # day-before reminder email for every upcoming booking
    reminder_before_hours: int = Field(default=24, alias="REMINDER_BEFORE_HOURS")
    # pre-call brief for the host (app/precall.py): lead score + brief in the "New booking" email, the day-before host email,
    # and one alert per hot lead that left an email but booked nothing
    precall_enabled: bool = Field(default=True, alias="PRECALL_ENABLED")
    precall_use_model: bool = Field(default=True, alias="PRECALL_USE_MODEL")          # false = rule-based brief only
    precall_model: str = Field(default="", alias="PRECALL_MODEL")                     # empty = CHAT_MODEL
    precall_model_timeout: int = Field(default=25, alias="PRECALL_MODEL_TIMEOUT")     # seconds; the brief falls back to rules after this
    precall_host_reminder: bool = Field(default=True, alias="PRECALL_HOST_REMINDER")  # "Brief for tomorrow" to the host
    hot_lead_alerts: bool = Field(default=True, alias="HOT_LEAD_ALERTS")
    # "Email Deep" (app/escalate.py): the hand-over form is prefilled with an email the assistant writes from the chat, and
    # Deep gets a summary (need, open questions, the chat). false = the older plain hand-over email
    handover_summary: bool = Field(default=True, alias="HANDOVER_SUMMARY")
    # visitor detections (app/intent.py): job seekers, students and sellers are pointed elsewhere instead of to Deep's calendar;
    # a visitor showing real buying signs (price, volume, deadline, budget) is offered a call and Deep is told at once.
    # Each can also be switched off in the console (Detections); these are the install-wide defaults
    wrong_fit_detection: bool = Field(default=True, alias="WRONG_FIT_DETECTION")
    buying_detection: bool = Field(default=True, alias="BUYING_DETECTION")
    buying_alerts: bool = Field(default=True, alias="BUYING_ALERTS")                  # the "hot visitor on the site now" email
    # compare side by side (app/compare.py): "X vs Y" questions get each side's own pages and a table card
    compare_enabled: bool = Field(default=True, alias="COMPARE_ENABLED")
    # "Email me this chat" (app/chat_email.py): the visitor gets the conversation by email; their address is kept as a lead
    chat_email_enabled: bool = Field(default=True, alias="CHAT_EMAIL_ENABLED")
    hot_lead_score: int = Field(default=60, alias="HOT_LEAD_SCORE")
    # knowledge-gap loop (app/gaps.py): nightly drafts for unanswered questions; an approved draft becomes a custom answer
    # and (GAP_FOLLOWUP) the people who asked get the answer by email
    gap_loop_enabled: bool = Field(default=True, alias="GAP_LOOP_ENABLED")
    gap_cron: str = Field(default="20 3 * * *", alias="GAP_CRON")                     # host timezone; after the 02:30 re-crawl
    gap_days: int = Field(default=30, alias="GAP_DAYS")                               # look-back for unanswered questions
    gap_max_drafts: int = Field(default=10, alias="GAP_MAX_DRAFTS")                   # new drafts (model calls) per night
    gap_similarity: float = Field(default=0.78, alias="GAP_SIMILARITY")               # same question, other words (bge-small cosine: rewordings 0.76-0.97, different questions up to 0.75)
    gap_model: str = Field(default="", alias="GAP_MODEL")                             # empty = CHAT_MODEL
    gap_followup: bool = Field(default=True, alias="GAP_FOLLOWUP")
    gap_followup_max_days: int = Field(default=45, alias="GAP_FOLLOWUP_MAX_DAYS")     # only people who asked this recently
    # call outcomes (app/outcomes.py): "how did it go?" to the host after each call, follow-up drafts, and a lead score
    # that re-weights its rules from the outcomes once SCORE_LEARN_MIN calls are rated
    outcomes_enabled: bool = Field(default=True, alias="OUTCOMES_ENABLED")
    outcome_ask_after_minutes: int = Field(default=20, alias="OUTCOME_ASK_AFTER_MINUTES")
    score_learning: bool = Field(default=True, alias="SCORE_LEARNING")
    score_learn_min: int = Field(default=20, alias="SCORE_LEARN_MIN")
    # lead score inputs (app/precall.py), all comma lists
    score_call_types: str = Field(default="lakeb2b-product-walkthrough-use-case-demo:10,gtm-strategy-session-data-ai-revenue-acceleration:8,"
                                          "discovery-call:0", alias="SCORE_CALL_TYPES")  # slug:points; unknown slugs fall back to keywords/duration
    score_internal_domains: str = Field(default="championsmail.com,lakeb2b.com,ampliz.com,spanglobalservices.com,deependhq.com",
                                        alias="SCORE_INTERNAL_DOMAINS")  # staff/test: -50, never a lead, never learned from
    score_internal_emails: str = Field(default="", alias="SCORE_INTERNAL_EMAILS")  # extra exact addresses (+tags ignored); HOST_EMAIL is always internal
    score_competitor_domains: str = Field(default="zoominfo.com,apollo.io,lusha.com,cognism.com,seamless.ai,uplead.com,rocketreach.co,"
                                                  "clearbit.com,6sense.com,leadiq.com,datanyze.com,kaspr.io", alias="SCORE_COMPETITOR_DOMAINS")
    score_target_countries: str = Field(default="", alias="SCORE_TARGET_COUNTRIES")  # ISO2 from sessions.country_code, e.g. US,GB; empty = rule off
    score_brands: str = Field(default="", alias="SCORE_BRANDS")  # extra brand names for the brand-claim check
    score_key_pages: str = Field(default="/pricing,/plans,/contact,/request-demo,/company/lake-b2b", alias="SCORE_KEY_PAGES")  # path prefixes on deependhq.com, not the assistant host
    domain_check: bool = Field(default=True, alias="DOMAIN_CHECK")  # DNS MX/A check of business email domains, worker threads only; tests turn it off
    domain_check_fallback_ns: str = Field(default="1.1.1.1,8.8.8.8", alias="DOMAIN_CHECK_FALLBACK_NS")  # tried once after the system resolver fails, while time remains; empty = system resolver only; they see the domain only, never the address
    link_secret: str = Field(default="", alias="LINK_SECRET")  # signs one-tap email links; empty = derived from ADMIN_TOKEN
    enrich_enabled: bool = Field(default=True, alias="ENRICH_ENABLED")
    suggestions_days: int = Field(default=30, alias="SUGGESTIONS_DAYS")
    multilingual: bool = Field(default=True, alias="MULTILINGUAL")
    voice_languages: str = Field(default="auto,en,hi,te,ta,bn,es,fr,de", alias="VOICE_LANGUAGES")  # call view language picker
    visitor_memory: bool = Field(default=True, alias="VISITOR_MEMORY")  # return-visitor memory in the greeting and prompt
    # Working memory (docs/MEMORY_VOICE.md): CURRENT CONVERSATION facts per session; HISTORY stays under VISITOR_MEMORY
    working_memory: bool = Field(default=True, alias="WORKING_MEMORY")
    memory_extract: bool = Field(default=True, alias="MEMORY_EXTRACT")                # small-model extraction at the window edge, catch-up, precall, rebuild; false = rules only
    memory_model: str = Field(default="", alias="MEMORY_MODEL")                       # empty = CHAT_MODEL
    memory_model_timeout: int = Field(default=8, alias="MEMORY_MODEL_TIMEOUT")        # seconds per extraction call (no retries); rules only after this
    memory_model_max_tokens: int = Field(default=300, alias="MEMORY_MODEL_MAX_TOKENS")  # raise to 800+ for a reasoning model such as gpt-oss-120b
    memory_max_chars: int = Field(default=1200, alias="MEMORY_MAX_CHARS")            # cap for the CURRENT CONVERSATION block
    memory_history_max_chars: int = Field(default=1400, alias="MEMORY_HISTORY_MAX_CHARS")  # cap for the HISTORY block
    memory_history_sessions: int = Field(default=4, alias="MEMORY_HISTORY_SESSIONS")  # earlier conversations shown and caught up
    memory_stale_days: int = Field(default=90, alias="MEMORY_STALE_DAYS")             # need/buying facts older than this: "may be out of date"
    memory_retention_days: int = Field(default=365, alias="MEMORY_RETENTION_DAYS")    # session_memory rows older than this are purged (tombstones kept)
    # Ask Deep panel in the visitor and guest booking emails (app/email_ask.py, docs/EMAILS.md)
    email_ask_enabled: bool = Field(default=True, alias="EMAIL_ASK_ENABLED")
    email_ask_target: str = Field(default="assistant", alias="EMAIL_ASK_TARGET")      # assistant (PUBLIC_BASE_URL/ask) | site (deependhq.com's widget)
    email_ask_ttl_days: int = Field(default=30, alias="EMAIL_ASK_TTL_DAYS")           # links work until this many days after the call
    email_ask_autosend: bool = Field(default=True, alias="EMAIL_ASK_AUTOSEND")        # a tapped question is sent once the page is really open
    email_ask_bind_history: bool = Field(default=True, alias="EMAIL_ASK_BIND_HISTORY")  # the booker's earlier website chats join this device's memory
    outreach_enabled: bool = Field(default=True, alias="OUTREACH_ENABLED")  # proactive outreach rules (docs/OUTREACH.md)
    # returning visitors who never chatted and their network (docs/OUTREACH.md "Returning visitors and their network")
    outreach_visitors: bool = Field(default=True, alias="OUTREACH_VISITORS")  # a visitors row per device for page views without a chat; needs TRACKING_ENABLED
    outreach_visit_gap_min: int = Field(default=30, alias="OUTREACH_VISIT_GAP_MIN")  # minutes without a check before the next one counts as a new visit
    outreach_ip_context: bool = Field(default=True, alias="OUTREACH_IP_CONTEXT")  # hard switch; the console also has a soft switch (settings key outreach:ip_context)
    outreach_company_kinds: str = Field(default="corporate", alias="OUTREACH_COMPANY_KINDS")  # kinds named without approval; education/government/unknown become console candidates
    outreach_country: bool = Field(default=True, alias="OUTREACH_COUNTRY")  # {country} in pop-ups
    outreach_no_personalise_countries: str = Field(
        default="AT,BE,BG,HR,CY,CZ,DK,EE,FI,FR,DE,GR,HU,IE,IT,LV,LT,LU,MT,NL,PL,PT,RO,SK,SI,ES,SE,IS,LI,NO,GB,CH",
        alias="OUTREACH_NO_PERSONALISE_COUNTRIES")  # no IP context there; while non-empty, a browser tz under Europe/ skips the visitors row and the lookup entirely. Clear it only with a consent banner.
    outreach_honor_gpc: bool = Field(default=True, alias="OUTREACH_HONOR_GPC")  # Global Privacy Control / DNT: no visitors row, no lookup, no IP context
    outreach_geo_daily_cap: int = Field(default=150, alias="OUTREACH_GEO_DAILY_CAP")  # page-view lookups per UTC day (in-process); they also count against GEOIP_DAILY_CAP
    outreach_dismiss_quiet_days: int = Field(default=14, alias="OUTREACH_DISMISS_QUIET_DAYS")  # after closing any 'never chatted' pop-up
    # Answer cards (docs/UI_CARDS.md): one optional openui-lang block per answer, rendered by static/deep-ui.js
    ui_cards_enabled: bool = Field(default=True, alias="UI_CARDS_ENABLED")
    ui_cards_max_chars: int = Field(default=4000, alias="UI_CARDS_MAX_CHARS")      # per-turn cap on the block
    ui_cards_max_tokens: int = Field(default=800, alias="UI_CARDS_MAX_TOKENS")     # completion cap on card-eligible turns (500 elsewhere)
    # Rich weekly digest (docs/AUTOMATIONS.md section 6): composed by the model in openui-lang, rendered to HTML by Node (tools/openui).
    # Sends the week's leads (name, email, company, reason) and visitor questions to the LLM provider in one call.
    digest_rich_email: bool = Field(default=True, alias="DIGEST_RICH_EMAIL")
    digest_model: str = Field(default="", alias="DIGEST_MODEL")                    # empty = CHAT_MODEL
    digest_model_timeout: int = Field(default=60, alias="DIGEST_MODEL_TIMEOUT")    # seconds for the composing call
    digest_render_timeout: int = Field(default=60, alias="DIGEST_RENDER_TIMEOUT")  # seconds for node tools/openui/render_email.mjs
    digest_node: str = Field(default="", alias="DIGEST_NODE")                      # node binary; empty = "node" on PATH

    # In-chat booking (docs/BOOKING.md)
    booking_days_ahead: int = Field(default=14, alias="BOOKING_DAYS_AHEAD")
    availability_cache_seconds: int = Field(default=60, alias="AVAILABILITY_CACHE_SECONDS")
    host_hours: str = Field(default="", alias="HOST_HOURS")  # "09:00-18:00" in HOST_TIMEZONE; empty = inferred from open slots
    booking_max_active_per_email: int = Field(default=2, alias="BOOKING_MAX_ACTIVE_PER_EMAIL")
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")  # where this service is reachable; used in email links
    # email images (static/email/*): a public https folder Gmail's image proxy can fetch; empty = embed them as cid parts.
    # No current email uses images (app/booking/email_html.py); the delivery mechanism is kept for one that does
    email_assets_url: str = Field(default="https://cdn.jsdelivr.net/gh/ajaykarthikpogula0101/deep-agent@main/static/email",
                                  alias="EMAIL_ASSETS_URL")
    host_name_short: str = Field(default="Deep", alias="HOST_NAME_SHORT")
    # the host card in visitor and guest emails: title under the name, and a square photo (public https URL, >= 96 px)
    host_full_name: str = Field(default="Sreedeep Surapaneni", alias="HOST_FULL_NAME")   # the host card's name
    host_title: str = Field(default="Founder & CMO, Champions Group", alias="HOST_TITLE")
    host_linkedin_url: str = Field(default="https://www.linkedin.com/in/sreedeep-surapaneni", alias="HOST_LINKEDIN_URL")
    host_photo_url: str = Field(default="", alias="HOST_PHOTO_URL")
    # postal address in every booking email's footer (mail providers trust mail that carries one); empty = no line
    email_postal_address: str = Field(default="Champions Square, Opp. Decathlon, Sarjapur Main Road, Carmelaram, Bengaluru 560035, India",
                                      alias="EMAIL_POSTAL_ADDRESS")
    demo_user_name: str = Field(default="Ada Lovelace", alias="DEMO_USER_NAME")
    demo_user_email: str = Field(default="ada@lovelace.org", alias="DEMO_USER_EMAIL")

    # Zoom
    zoom_account_id: str = Field(default="", alias="ZOOM_ACCOUNT_ID")
    zoom_client_id: str = Field(default="", alias="ZOOM_CLIENT_ID")
    zoom_client_secret: str = Field(default="", alias="ZOOM_CLIENT_SECRET")
    zoom_booking_user: str = Field(default="sreedeep", alias="ZOOM_BOOKING_USER")
    zoom_booking_base: str = Field(default="https://scheduler.zoom.us/sreedeep", alias="ZOOM_BOOKING_BASE")
    host_timezone: str = Field(default="Asia/Kolkata", alias="HOST_TIMEZONE")
    zoom_avail_param_from: str = Field(default="from", alias="ZOOM_AVAIL_PARAM_FROM")
    zoom_avail_param_to: str = Field(default="to", alias="ZOOM_AVAIL_PARAM_TO")
    zoom_avail_param_tz: str = Field(default="time_zone", alias="ZOOM_AVAIL_PARAM_TZ")
    zoom_enable_api_booking: bool = Field(default=False, alias="ZOOM_ENABLE_API_BOOKING")
    zoom_host_user_id: str = Field(default="", alias="ZOOM_HOST_USER_ID")  # host's user id or email for POST /users/{id}/meetings
    zoom_booking_test_url: str = Field(default="", alias="ZOOM_BOOKING_TEST_URL")  # a scheduler page in YOUR account for live browser tests

    # Browser booking on the public scheduler page (docs/BROWSER_BOOKING.md): no Zoom credentials needed
    browser_booking_enabled: bool = Field(default=False, alias="BROWSER_BOOKING_ENABLED")
    browser_booking_driver: str = Field(default="auto", alias="BROWSER_BOOKING_DRIVER")  # auto | jev (TypeSafe) | script (no model)
    browser_booking_dry_run: bool = Field(default=False, alias="BROWSER_BOOKING_DRY_RUN")  # fill but never press Book (testing)
    browser_booking_timeout: int = Field(default=240, alias="BROWSER_BOOKING_TIMEOUT")
    typesafe_api_key: str = Field(default="", alias="TYPESAFE_API_KEY")
    typesafe_model: str = Field(default="jev-latest", alias="TYPESAFE_MODEL")
    text_model_api_key: str = Field(default="", alias="TEXT_MODEL_API_KEY")  # empty = the chat model key
    text_model_base_url: str = Field(default="", alias="TEXT_MODEL_BASE_URL")  # empty = LLM_BASE_URL
    text_model: str = Field(default="", alias="TEXT_MODEL")  # empty = CHAT_MODEL
    text_model_reasoning: str = Field(default="none", alias="TEXT_MODEL_REASONING")
    jev_python: str = Field(default="", alias="JEV_PYTHON")  # interpreter of the jev environment (Python 3.12)
    jev_browser_path: str = Field(default="", alias="JEV_BROWSER_PATH")  # Chrome/Edge binary; empty = auto-detect
    jev_cdp_url: str = Field(default="", alias="JEV_CDP_URL")  # an already running browser (http://127.0.0.1:9222); empty = the app keeps one
    jev_persistent_browser: bool = Field(default=True, alias="JEV_PERSISTENT_BROWSER")  # false = the worker launches a browser per run
    # The Zoom link for browser bookings (app/booking/zoom_mail.py): the worker adds this mailbox as an attendee on Zoom, and
    # the app reads Zoom's invitation there over IMAP for the join link, meeting ID and passcode. No Zoom credentials.
    zoom_link_from_email: bool = Field(default=True, alias="ZOOM_LINK_FROM_EMAIL")
    zoom_link_mailbox: str = Field(default="", alias="ZOOM_LINK_MAILBOX")  # empty = SMTP_USER
    zoom_link_imap_host: str = Field(default="imap.gmail.com", alias="ZOOM_LINK_IMAP_HOST")
    zoom_link_imap_password: str = Field(default="", alias="ZOOM_LINK_IMAP_PASSWORD")  # empty = SMTP_PASSWORD
    zoom_link_wait_seconds: int = Field(default=90, alias="ZOOM_LINK_WAIT_SECONDS")  # how long the confirmation emails wait for it

    # Email
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", validation_alias=AliasChoices("SMTP_PASSWORD", "SMTP_PASS"))
    email_from: str = Field(default="assistant@deependhq.com", validation_alias=AliasChoices("EMAIL_FROM", "SMTP_FROM"))
    host_email: str = Field(default="deep@championsmail.com", alias="HOST_EMAIL")

    @property
    def chat_api_key(self) -> str:
        return self.llm_api_key or self.openai_api_key

    @property
    def origins(self) -> list[str]:
        # No wildcard, ever. Empty entries are dropped.
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip() and o.strip() != "*"]

    @property
    def mmdb_dir(self) -> str:
        """Where the GeoLite2 files live: GEOIP_MMDB_DIR, else data/geoip once a MaxMind key is set ('' = not configured)."""
        return self.geoip_mmdb_dir or ("data/geoip" if self.maxmind_license_key else "")

    @property
    def zoom_api_configured(self) -> bool:
        return bool(self.zoom_account_id and self.zoom_client_id and self.zoom_client_secret)


settings = Settings()
