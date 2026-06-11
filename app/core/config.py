"""
app/core/config.py
Single source of truth for all application configuration.
Uses pydantic-settings to load values from environment/.env file.
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application
    app_name: str = "semantic-scraper"
    app_env: str = "development"
    log_level: str = "INFO"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # LLM
    openai_api_key: str = "sk-placeholder"
    # Gemini 1.5 Pro: 2M token context window tablolarÄ± ve bÃ¼yÃ¼k sayfalarÄ±
    # tek seferde okuyabilir. Groq/OpenAI iÃ§in de Ã§alÄ±ÅŸÄ±r, sadece .env'yi gÃ¼ncelle.
    llm_model: str = "gemini-1.5-pro"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.2
    # Optional: override to use Groq, Together.ai, Ollama, Gemini, etc.
    # Leave empty to use the default OpenAI endpoint.
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_provider: str = "gemini"  # openai | groq | ollama | gemini | custom
    # Karakter sÄ±nÄ±rÄ±: Gemini 1.5 Pro ~14M char okuyabilir.
    # Groq kullanÄ±yorsan 38_000 ile dÃ¼ÅŸÃ¼r. 0 = sÄ±nÄ±rsÄ±z.
    llm_max_content_chars: int = 500_000
    
    # Token tasarrufu iÃ§in hedeflenen karakter boyutu (sÄ±nÄ±r aÅŸÄ±lmasa bile her zaman bu boyuta kÄ±rpÄ±lÄ±r)
    llm_target_content_chars: int = 15_000

    # Scraper
    scraper_default_timeout_ms: int = 30_000
    scraper_headless: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached singleton of Settings.
    Use `get_settings.cache_clear()` in tests to reset.
    """
    return Settings()
