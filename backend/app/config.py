"""Settings, read from .env. See .env.example."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "medium"          # opus-5-5 defaults to medium

    protected_store_path: str = "./protected_store"
    database_url: str = "sqlite:///./privacy_review.db"

    # When true, the API layer refuses to serialise any raw entity value.
    enforce_no_raw_pii: bool = True


settings = Settings()
