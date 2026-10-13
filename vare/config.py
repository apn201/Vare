"""Settings from the environment.

Plain dataclass rather than pydantic-settings: five values do not need another
dependency. `.env` in the repo root (or private/.env) is loaded for dev; real
environment variables always win.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_QLOO_BASE_URL = "https://hackathon.api.qloo.com"


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"


def _env(*names: str, default: str = "") -> str:
    """First non-empty value among `names`, matched case-insensitively (Linux
    keeps `LLM_key` and `LLM_KEY` apart; Windows does not). Lets the short dev
    names (KEY, BASE_URL, LLM_KEY) work alongside the documented ones."""
    lowered = {k.lower(): v for k, v in os.environ.items()}
    for name in names:
        value = lowered.get(name.lower(), "").strip()
        if value:
            return value
    return default


@dataclass(frozen=True)
class Settings:
    qloo_api_key: str
    qloo_base_url: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    qloo_cache_path: str
    debug_retain_traces: bool
    llm_reasoning: str = ""   # OpenRouter: "off" disables thinking, "low"|"medium"|"high" sets effort; "" sends nothing
    qloo_month_reserve: int = 300  # stop calling Qloo when this few monthly calls remain
    qloo_timeout_s: float = 15.0   # spec said 10; tag-signal insights cold calls measured >10 s
    llm_timeout_s: float = 90.0

    @property
    def qloo_stub(self) -> bool:
        return not self.qloo_api_key or self.qloo_api_key == "stub"

    @property
    def llm_key_set(self) -> bool:
        return bool(self.llm_api_key)

    def secrets(self) -> list[str]:
        """Every value that must never leave the server."""
        return [s for s in (self.qloo_api_key, self.llm_api_key) if s and s != "stub"]


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / "private" / ".env", override=False)
    llm_key = _env("LLM_API_KEY", "LLM_KEY", "OPENROUTER_API_KEY")
    # An OpenRouter key (sk-or-...) implies the OpenRouter endpoint unless told otherwise.
    openrouter = llm_key.startswith("sk-or-")
    return Settings(
        qloo_api_key=_env("QLOO_API_KEY", "KEY"),
        qloo_base_url=_env("QLOO_BASE_URL", "BASE_URL", default=DEFAULT_QLOO_BASE_URL).rstrip("/"),
        llm_base_url=_env("LLM_BASE_URL", default=OPENROUTER_BASE_URL if openrouter else "https://api.openai.com/v1").rstrip("/"),
        llm_api_key=llm_key,
        llm_model=_env("LLM_MODEL", default=OPENROUTER_DEFAULT_MODEL if openrouter else "gpt-4o-mini"),
        qloo_cache_path=os.environ.get("QLOO_CACHE_PATH", "var/qloo_cache.db").strip(),
        debug_retain_traces=_env("DEBUG_RETAIN_TRACES").lower() in ("1", "true", "yes"),
        llm_reasoning=_env("LLM_REASONING", default="off" if openrouter else ""),
        qloo_month_reserve=int(_env("QLOO_MONTH_RESERVE", default="300")),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
