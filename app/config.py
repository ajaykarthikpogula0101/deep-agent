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
    # Embeddings: local Hugging Face model via fastembed (free, no key)
    embed_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBED_MODEL")

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
    retrieval_min_score: float = Field(default=0.60, alias="RETRIEVAL_MIN_SCORE")  # bge-small scale; see docs/TEST_LOG.md
    retrieval_top_k: int = Field(default=6, alias="RETRIEVAL_TOP_K")
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
    # text-to-speech: "browser" = SpeechSynthesis in the widget; "openai" = /audio/speech (OpenAI tts-1 or compatible)
    tts_provider: str = Field(default="browser", alias="TTS_PROVIDER")  # browser | openai
    tts_api_key: str = Field(default="", alias="TTS_API_KEY")
    tts_base_url: str = Field(default="https://api.openai.com/v1", alias="TTS_BASE_URL")
    tts_model: str = Field(default="tts-1", alias="TTS_MODEL")
    tts_voice: str = Field(default="alloy", alias="TTS_VOICE")
    trust_proxy: bool = Field(default=True, alias="TRUST_PROXY")  # honour CF-Connecting-IP / X-Forwarded-For

    # Session origin tracking (app/tracking.py)
    tracking_enabled: bool = Field(default=True, alias="TRACKING_ENABLED")
    geoip_provider: str = Field(default="ipwho", alias="GEOIP_PROVIDER")  # ipwho | ipinfo | ipapi | none
    geoip_token: str = Field(default="", alias="GEOIP_TOKEN")  # ipinfo only
    track_ip_mode: str = Field(default="full", alias="TRACK_IP_MODE")  # full | masked (/24, /48)
    track_retention_days: int = Field(default=90, alias="TRACK_RETENTION_DAYS")

    # Automations (docs/AUTOMATIONS.md): weekly digest, follow-up nudges, lead enrichment, smart suggestions, languages
    digest_enabled: bool = Field(default=True, alias="DIGEST_ENABLED")
    digest_cron: str = Field(default="0 9 * * 1", alias="DIGEST_CRON")  # Monday 09:00, host timezone
    nudge_enabled: bool = Field(default=True, alias="NUDGE_ENABLED")
    nudge_after_hours: int = Field(default=24, alias="NUDGE_AFTER_HOURS")
    enrich_enabled: bool = Field(default=True, alias="ENRICH_ENABLED")
    suggestions_days: int = Field(default=30, alias="SUGGESTIONS_DAYS")
    multilingual: bool = Field(default=True, alias="MULTILINGUAL")

    # In-chat booking (docs/BOOKING.md)
    booking_days_ahead: int = Field(default=14, alias="BOOKING_DAYS_AHEAD")
    availability_cache_seconds: int = Field(default=60, alias="AVAILABILITY_CACHE_SECONDS")
    host_hours: str = Field(default="", alias="HOST_HOURS")  # "09:00-18:00" in HOST_TIMEZONE; empty = inferred from open slots
    booking_max_active_per_email: int = Field(default=2, alias="BOOKING_MAX_ACTIVE_PER_EMAIL")
    public_base_url: str = Field(default="", alias="PUBLIC_BASE_URL")  # where this service is reachable; used in email links
    host_name_short: str = Field(default="Deep", alias="HOST_NAME_SHORT")
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
    def zoom_api_configured(self) -> bool:
        return bool(self.zoom_account_id and self.zoom_client_id and self.zoom_client_secret)


settings = Settings()
