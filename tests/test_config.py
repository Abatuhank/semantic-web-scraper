"""
tests/test_config.py
Config katmanÄ± testleri.

Test Edilen Dosya: app/core/config.py
Ne Test Ediliyor:
  1. VarsayÄ±lan ayarlarÄ±n doÄŸru yÃ¼klenip yÃ¼klenmediÄŸi
  2. Ortam deÄŸiÅŸkenleriyle override edilip edilmediÄŸi
  3. log_level validasyonunun Ã§alÄ±ÅŸÄ±p Ã§alÄ±ÅŸmadÄ±ÄŸÄ±
  4. get_settings() singleton (lru_cache) davranÄ±ÅŸÄ±
"""
import os

import pytest


class TestSettingsDefaults:
    """Settings sÄ±nÄ±fÄ±nÄ±n varsayÄ±lan deÄŸerlerinin doÄŸru olduÄŸunu doÄŸrular."""

    def test_default_app_name(self, mock_settings):
        """Girdi: Settings(app_name='semantic-scraper-test')
        Beklenen Ã‡Ä±ktÄ±: 'semantic-scraper-test'"""
        assert mock_settings.app_name == "semantic-scraper-test"

    def test_default_headless_mode(self, mock_settings):
        """Girdi: Settings(scraper_headless=True)
        Beklenen Ã‡Ä±ktÄ±: True"""
        assert mock_settings.scraper_headless is True

    def test_default_timeout(self, mock_settings):
        """Girdi: Settings(scraper_default_timeout_ms=10000)
        Beklenen Ã‡Ä±ktÄ±: 10000"""
        assert mock_settings.scraper_default_timeout_ms == 10_000

    def test_llm_temperature_range(self, mock_settings):
        """Girdi: Settings(llm_temperature=0.1)
        Beklenen Ã‡Ä±ktÄ±: 0.0 â‰¤ 0.1 â‰¤ 2.0"""
        assert 0.0 <= mock_settings.llm_temperature <= 2.0


class TestSettingsValidation:
    """Validasyon kurallarÄ±nÄ±n doÄŸru Ã§alÄ±ÅŸtÄ±ÄŸÄ±nÄ± doÄŸrular."""

    def test_valid_log_levels(self):
        """Girdi: log_level = 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
        Beklenen Ã‡Ä±ktÄ±: Hepsi kabul edilir (hata fÄ±rlatÄ±lmaz)"""
        from app.core.config import Settings

        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            s = Settings(log_level=level)
            assert s.log_level == level

    def test_invalid_log_level_raises(self):
        """Girdi: log_level = 'VERBOSE' (geÃ§ersiz)
        Beklenen Ã‡Ä±ktÄ±: ValidationError"""
        from app.core.config import Settings
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="log_level"):
            Settings(log_level="VERBOSE")

    def test_case_insensitive_log_level(self):
        """Girdi: log_level = 'debug' (kÃ¼Ã§Ã¼k harf)
        Beklenen Ã‡Ä±ktÄ±: 'DEBUG' (bÃ¼yÃ¼k harfe Ã§evrilir)"""
        from app.core.config import Settings

        s = Settings(log_level="debug")
        assert s.log_level == "DEBUG"


class TestSettingsSingleton:
    """lru_cache ile singleton davranÄ±ÅŸÄ±nÄ±n Ã§alÄ±ÅŸtÄ±ÄŸÄ±nÄ± doÄŸrular."""

    def test_get_settings_returns_same_instance(self):
        """get_settings() her Ã§aÄŸrÄ±da aynÄ± nesneyi dÃ¶ndÃ¼rmeli."""
        from app.core.config import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2, "lru_cache Ã§alÄ±ÅŸmÄ±yor â€” farklÄ± nesneler dÃ¶ndÃ¼"

    def test_cache_clear_creates_new_instance(self):
        """cache_clear() sonrasÄ± yeni bir nesne dÃ¶ndÃ¼rÃ¼lmeli."""
        from app.core.config import get_settings

        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # EÅŸdeÄŸer olabilir ama farklÄ± nesne olmalÄ±
        assert s1 is not s2, "cache_clear() sonrasÄ± aynÄ± nesne dÃ¶ndÃ¼"


class TestSettingsEnvOverride:
    """Ortam deÄŸiÅŸkenleriyle override edilip edilmediÄŸini doÄŸrular."""

    def test_env_override_app_name(self, monkeypatch):
        """Girdi: APP_NAME='my-custom-app' (ortam deÄŸiÅŸkeni)
        Beklenen Ã‡Ä±ktÄ±: settings.app_name == 'my-custom-app'"""
        from app.core.config import Settings

        monkeypatch.setenv("APP_NAME", "my-custom-app")
        s = Settings()
        assert s.app_name == "my-custom-app"

    def test_env_override_llm_model(self, monkeypatch):
        """Girdi: LLM_MODEL='gpt-4o-mini' (ortam deÄŸiÅŸkeni)
        Beklenen Ã‡Ä±ktÄ±: settings.llm_model == 'gpt-4o-mini'"""
        from app.core.config import Settings

        monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
        s = Settings()
        assert s.llm_model == "gpt-4o-mini"
