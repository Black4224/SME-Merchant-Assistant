"""Application configuration (environment variables / .env file)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"


def _real(value: str | None) -> bool:
    """False for empty values and for the placeholders shipped in .env.example (so copying that file unchanged is harmless)."""
    v = (value or "").strip().lower()
    return bool(v) and not (v.startswith("your_") or v.endswith("_here") or v in {"changeme", "xxx", "todo"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    database_url: str = f"sqlite:///{BACKEND_DIR / 'sme_assistant.db'}"
    cors_origins: str = "http://localhost:5173"

    ai_provider: str = "groq"
    groq_api_key: str | None = None
    groq_model: str | None = None
    # Opt-in: on a TRANSIENT provider failure, answer with the offline rules mode and label the reply as degraded.
    ai_fallback_to_rules: bool = False

    @property
    def ai_configured(self) -> bool:
        if self.ai_provider == "rules":  # offline keyword mode needs no key
            return True
        return _real(self.groq_api_key) and _real(self.groq_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
