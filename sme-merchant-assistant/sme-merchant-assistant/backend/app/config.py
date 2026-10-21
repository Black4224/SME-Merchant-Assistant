"""Application configuration (environment variables / .env file)."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"


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

    @property
    def ai_configured(self) -> bool:
        return bool(self.groq_api_key and self.groq_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
