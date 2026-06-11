"""
tests/conftest.py
Shared fixtures for all test modules.
"""
import os
import sys
import logging

import pytest

# Ensure the project root is importable
# This allows `from app.xxx import ...` to work even when pytest is invoked
# from the tests/ directory.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# Clear the Settings cache before each test
@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Reset the lru_cache on get_settings so env overrides work per-test."""
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# Provide a Settings instance that never touches real APIs
@pytest.fixture()
def mock_settings():
    """Return a Settings object with safe defaults for testing."""
    from app.core.config import Settings
    return Settings(
        app_name="semantic-scraper-test",
        app_env="testing",
        log_level="DEBUG",
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://localhost:6379/0",
        celery_result_backend="redis://localhost:6379/1",
        openai_api_key="sk-test-key",
        llm_model="test-model",
        llm_base_url="https://fake-llm.test/v1",
        llm_provider="openai",
        llm_max_tokens=512,
        llm_temperature=0.1,
        llm_max_content_chars=5000,
        llm_target_content_chars=3000,
        scraper_default_timeout_ms=10_000,
        scraper_headless=True,
    )


# Provide a standard logger
@pytest.fixture()
def test_logger():
    """Return a simple logger for service tests."""
    logger = logging.getLogger("test")
    logger.setLevel(logging.DEBUG)
    return logger
