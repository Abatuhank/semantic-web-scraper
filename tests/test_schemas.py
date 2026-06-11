"""
tests/test_schemas.py
Pydantic veri modeli testleri.

Test Edilen Dosya: app/models/schemas.py
Ne Test Ediliyor:
  1. ScrapeRequest â€” URL validasyonu, boÅŸ query reddi, timeout sÄ±nÄ±rlarÄ±
  2. DeepScrapeRequest â€” max_pages aralÄ±ÄŸÄ±, link_pattern sanitizasyonu
  3. JobStatus enum deÄŸerleri
  4. ScrapeResult ve DeepScrapeResult model_dump() Ã§Ä±ktÄ±larÄ±
"""
import pytest
from pydantic import ValidationError

from app.models.schemas import (
    DeepScrapeRequest,
    DeepScrapeResult,
    JobStatus,
    JobStatusResponse,
    ScrapeJobResponse,
    ScrapeRequest,
    ScrapeResult,
)


#  ScrapeRequest

class TestScrapeRequest:

    def test_valid_request(self):
        """Girdi: url='https://example.com', query='test query'
        Beklenen: HatasÄ±z oluÅŸturulur, URL HttpUrl olarak parse edilir"""
        req = ScrapeRequest(url="https://example.com", query="test query")
        assert str(req.url) == "https://example.com/"
        assert req.query == "test query"
        assert req.timeout_ms is None

    def test_invalid_url_rejected(self):
        """Girdi: url='not-a-url'
        Beklenen: ValidationError (geÃ§ersiz URL)"""
        with pytest.raises(ValidationError, match="url"):
            ScrapeRequest(url="not-a-url", query="test")

    def test_empty_query_rejected(self):
        """Girdi: query='   ' (sadece boÅŸluk)
        Beklenen: ValidationError (boÅŸ query)"""
        with pytest.raises(ValidationError, match="query must not be empty"):
            ScrapeRequest(url="https://example.com", query="   ")

    def test_query_gets_stripped(self):
        """Girdi: query='  test query  '
        Beklenen: 'test query' (baÅŸtaki/sondaki boÅŸluklar temizlenir)"""
        req = ScrapeRequest(url="https://example.com", query="  test query  ")
        assert req.query == "test query"

    def test_timeout_zero_becomes_none(self):
        """Girdi: timeout_ms=0
        Beklenen: None (0 = varsayÄ±lan kullan)"""
        req = ScrapeRequest(url="https://example.com", query="test", timeout_ms=0)
        assert req.timeout_ms is None

    def test_timeout_negative_becomes_none(self):
        """Girdi: timeout_ms=-5000
        Beklenen: None (negatif = varsayÄ±lan kullan)"""
        req = ScrapeRequest(url="https://example.com", query="test", timeout_ms=-5000)
        assert req.timeout_ms is None

    def test_timeout_exceeds_max_rejected(self):
        """Girdi: timeout_ms=200000 (2 dakikadan fazla)
        Beklenen: ValidationError"""
        with pytest.raises(ValidationError, match="timeout_ms cannot exceed 120000"):
            ScrapeRequest(url="https://example.com", query="test", timeout_ms=200_000)

    def test_valid_timeout_accepted(self):
        """Girdi: timeout_ms=60000
        Beklenen: 60000 (geÃ§erli)"""
        req = ScrapeRequest(url="https://example.com", query="test", timeout_ms=60_000)
        assert req.timeout_ms == 60_000

    def test_http_url_also_accepted(self):
        """Girdi: url='http://example.com' (HTTPS deÄŸil)
        Beklenen: Kabul edilir"""
        req = ScrapeRequest(url="http://example.com", query="test")
        assert "http" in str(req.url)


#  DeepScrapeRequest

class TestDeepScrapeRequest:

    def test_valid_deep_request(self):
        """Girdi: url, query, max_pages=5, link_pattern='/product/'
        Beklenen: HatasÄ±z oluÅŸturulur"""
        req = DeepScrapeRequest(
            url="https://example.com",
            query="en ucuz Ã¼rÃ¼n",
            max_pages=5,
            link_pattern="/product/",
        )
        assert req.max_pages == 5
        assert req.link_pattern == "/product/"

    def test_default_max_pages(self):
        """Girdi: max_pages belirtilmez
        Beklenen: 10 (varsayÄ±lan)"""
        req = DeepScrapeRequest(url="https://example.com", query="test")
        assert req.max_pages == 10

    def test_max_pages_too_high_rejected(self):
        """Girdi: max_pages=200 (100'den fazla)
        Beklenen: ValidationError"""
        with pytest.raises(ValidationError, match="max_pages must be between 1 and 100"):
            DeepScrapeRequest(
                url="https://example.com", query="test", max_pages=200
            )

    def test_max_pages_zero_rejected(self):
        """Girdi: max_pages=0
        Beklenen: ValidationError"""
        with pytest.raises(ValidationError, match="max_pages must be between 1 and 100"):
            DeepScrapeRequest(
                url="https://example.com", query="test", max_pages=0
            )

    def test_link_pattern_string_sanitized(self):
        """Girdi: link_pattern='string' (Swagger default placeholder)
        Beklenen: None (temizlenir)"""
        req = DeepScrapeRequest(
            url="https://example.com", query="test", link_pattern="string"
        )
        assert req.link_pattern is None

    def test_link_pattern_none_sanitized(self):
        """Girdi: link_pattern='none'
        Beklenen: None"""
        req = DeepScrapeRequest(
            url="https://example.com", query="test", link_pattern="none"
        )
        assert req.link_pattern is None

    def test_link_pattern_empty_sanitized(self):
        """Girdi: link_pattern='  '
        Beklenen: None"""
        req = DeepScrapeRequest(
            url="https://example.com", query="test", link_pattern="  "
        )
        assert req.link_pattern is None


#  JobStatus Enum

class TestJobStatus:

    def test_all_enum_values(self):
        """JobStatus enum'unun 4 deÄŸeri olmalÄ±."""
        assert set(JobStatus) == {
            JobStatus.QUEUED,
            JobStatus.PROCESSING,
            JobStatus.DONE,
            JobStatus.FAILED,
        }

    def test_enum_string_values(self):
        """Enum string karÅŸÄ±lÄ±klarÄ± doÄŸru olmalÄ±."""
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.PROCESSING.value == "processing"
        assert JobStatus.DONE.value == "done"
        assert JobStatus.FAILED.value == "failed"


#  Response Models

class TestResponseModels:

    def test_scrape_job_response_defaults(self):
        """Girdi: ScrapeJobResponse(job_id='abc-123')
        Beklenen: status=QUEUED, message varsayÄ±lan"""
        resp = ScrapeJobResponse(job_id="abc-123")
        assert resp.status == JobStatus.QUEUED
        assert "abc-123" not in resp.message  # mesajda job_id template'i yok

    def test_job_status_response_done(self):
        """Girdi: JobStatusResponse(job_id='x', status=DONE, result={'answer': 'test'})
        Beklenen: result eriÅŸilebilir, error None"""
        resp = JobStatusResponse(
            job_id="x", status=JobStatus.DONE, result={"answer": "test"}
        )
        assert resp.result == {"answer": "test"}
        assert resp.error is None

    def test_job_status_response_failed(self):
        """Girdi: JobStatusResponse(job_id='x', status=FAILED, error='timeout')
        Beklenen: error mesajÄ± mevcut, result None"""
        resp = JobStatusResponse(
            job_id="x", status=JobStatus.FAILED, error="timeout"
        )
        assert resp.result is None
        assert resp.error == "timeout"


#  Result Models

class TestResultModels:

    def test_scrape_result_model_dump(self):
        """ScrapeResult.model_dump() doÄŸru dict dÃ¶ndÃ¼rmeli."""
        result = ScrapeResult(
            url="https://example.com",
            query="test",
            raw_text_length=1500,
            llm_answer="Cevap budur.",
        )
        d = result.model_dump()
        assert d["url"] == "https://example.com"
        assert d["raw_text_length"] == 1500
        assert d["llm_answer"] == "Cevap budur."

    def test_deep_scrape_result_model_dump(self):
        """DeepScrapeResult.model_dump() doÄŸru dict dÃ¶ndÃ¼rmeli."""
        result = DeepScrapeResult(
            index_url="https://example.com",
            query="en ucuz",
            total_pages_visited=5,
            combined_text_length=8000,
            llm_answer="En ucuz Ã¼rÃ¼n: 49.90 TL",
        )
        d = result.model_dump()
        assert d["total_pages_visited"] == 5
        assert d["combined_text_length"] == 8000
        assert "49.90" in d["llm_answer"]
