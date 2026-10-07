"""Rate limiting + daily spend cap. In-memory sliding windows (single instance); swap for Redis when scaling."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.config import settings
from app.db import add_spend, spend_today

# List prices in USD per 1M tokens (input, output). Keys are the bare model name; a provider prefix such as
# "openai/" (OpenRouter) and a ":free" / ":batch" suffix are stripped before lookup. Update when models change.
PRICES = {
    # OpenAI (direct or via OpenRouter)
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-oss-120b": (0.04, 0.17),
    "gpt-oss-20b": (0.02, 0.09),
    # others commonly reachable through OpenRouter
    "claude-haiku-4.5": (1.00, 5.00),
    "claude-sonnet-4.5": (3.00, 15.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "llama-3.3-70b-instruct": (0.10, 0.30),
    "llama-3.1-8b-instruct": (0.05, 0.08),
    "mistral-nemo": (0.02, 0.03),
    "deepseek-v4-flash": (0.03, 1.28),
    # Groq (free tier bills nothing; we still count so the cap means something)
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "qwen3.8-27b": (0.29, 0.59),
}


def _bare(model: str) -> str:
    name = model.split("/", 1)[1] if "/" in model else model
    return name.split(":", 1)[0]


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int):
        self.per_minute, self.per_day = per_minute, per_day
        self._min: dict[str, deque] = defaultdict(deque)
        self._day: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            m, d = self._min[key], self._day[key]
            while m and m[0] < now - 60:
                m.popleft()
            while d and d[0] < now - 86400:
                d.popleft()
            if len(m) >= self.per_minute or len(d) >= self.per_day:
                return False
            m.append(now)
            d.append(now)
            return True


limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    if model.endswith(":free"):
        return 0.0
    pin, pout = PRICES.get(_bare(model), (2.00, 8.00))  # unknown model: assume expensive
    return prompt_tokens / 1e6 * pin + completion_tokens / 1e6 * pout


def spend_cap_reached() -> bool:
    try:
        return spend_today() >= settings.daily_spend_cap_usd
    except Exception:
        return False  # DB hiccup should not take the bot down; the ledger catches up on the next write


def record_spend(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    try:
        return add_spend(estimate_cost(model, prompt_tokens, completion_tokens))
    except Exception:
        return 0.0
