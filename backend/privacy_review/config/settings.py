"""Runtime settings, read from environment variables / .env. Never hardcode keys."""

from __future__ import annotations

import secrets
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"), extra="ignore"
    )

    # --- Claude ---------------------------------------------------------------
    anthropic_api_key: SecretStr | None = None
    # Minimal-usage defaults: the cheapest current model, low effort, no extended thinking,
    # short outputs, and a hard cap on calls per batch. Every LLM step is optional anyway.
    llm_model: str = "claude-haiku-5-5"
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    llm_thinking: Literal["disabled", "adaptive"] = "disabled"
    llm_enabled: bool = True                     # still requires a key to take effect
    llm_raw_text_detection: bool = False         # send RAW text to the LLM in Agent 1? off by default
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 1
    llm_max_tokens: int = 1024
    llm_max_calls_per_batch: int = Field(default=3, ge=0)

    # --- detection ------------------------------------------------------------
    spacy_model: str = "en_core_web_lg"
    presidio_score_threshold: float = 0.40
    verification_score_threshold: float = 0.30   # Agent 4 is deliberately more aggressive

    # --- pipeline -------------------------------------------------------------
    max_remediation_rounds: int = 2
    pseudonym_secret: SecretStr | None = None
    pseudonym_persist: bool = True               # keyed-hash mapping in protected_store/ (needs the secret)
    context_window_chars: int = 80

    # --- ingestion / API limits ---------------------------------------------
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    max_document_chars: int = Field(default=200_000, ge=1)
    max_files_per_batch: int = Field(default=20, ge=1)

    # --- paths ----------------------------------------------------------------
    knowledge_base_json: Path = BACKEND_DIR / "privacy_review" / "knowledge_base" / "policies.json"
    data_dir: Path = REPO_DIR / "data"
    protected_store_dir: Path = REPO_DIR / "protected_store"
    reports_dir: Path = REPO_DIR / "reports"

    # --- datasets -------------------------------------------------------------
    ai4privacy_sample_size: int = Field(default=400, ge=10)
    piimb_sample_size: int = Field(default=300, ge=10)
    random_seed: int = 247

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_enabled and self.anthropic_api_key and self.anthropic_api_key.get_secret_value())

    def pseudonym_key(self) -> bytes:
        if self.pseudonym_secret and self.pseudonym_secret.get_secret_value():
            return self.pseudonym_secret.get_secret_value().encode()
        warnings.warn(
            "PSEUDONYM_SECRET not set - using a random per-process key. Pseudonyms will not "
            "be stable across runs.",
            stacklevel=2,
        )
        return _ephemeral_key()


@lru_cache
def _ephemeral_key() -> bytes:
    return secrets.token_bytes(32)


@lru_cache
def get_settings() -> Settings:
    return Settings()
