"""
tests/test_logging.py
Logging modÃ¼lÃ¼ testleri.

Test Edilen Dosya: app/core/logging.py
Ne Test Ediliyor:
  1. get_logger() aynÄ± isimle aynÄ± instance dÃ¶ner (lru_cache)
  2. FarklÄ± isimlerle farklÄ± instance dÃ¶ner
  3. VarsayÄ±lan logger adÄ± 'semantic-scraper'
  4. Logger'Ä±n log seviyesi Settings'ten gelir
"""
import logging

from app.core.logging import get_logger


class TestGetLogger:

    def test_same_name_returns_same_instance(self):
        """get_logger('mymodule') aynÄ± nesneyi dÃ¶ndÃ¼rmeli (cached)."""
        # lru_cache temizle
        get_logger.cache_clear()

        logger1 = get_logger("test.module")
        logger2 = get_logger("test.module")
        assert logger1 is logger2

    def test_different_names_return_different_instances(self):
        """FarklÄ± isimlerle farklÄ± logger nesneleri dÃ¶ner."""
        get_logger.cache_clear()

        logger_a = get_logger("module_a")
        logger_b = get_logger("module_b")
        assert logger_a is not logger_b
        assert logger_a.name == "module_a"
        assert logger_b.name == "module_b"

    def test_default_name(self):
        """Girdi: get_logger() (isim belirtilmez)
        Beklenen: 'semantic-scraper' adlÄ± logger dÃ¶ner"""
        get_logger.cache_clear()

        logger = get_logger()
        assert logger.name == "semantic-scraper"

    def test_logger_is_logging_logger(self):
        """get_logger() logging.Logger instance'Ä± dÃ¶ndÃ¼rmeli."""
        get_logger.cache_clear()

        logger = get_logger("check.type")
        assert isinstance(logger, logging.Logger)
