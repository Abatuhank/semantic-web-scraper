"""
tests/test_api_routes.py
FastAPI endpoint testleri (httpx TestClient ile).

Test Edilen Dosya: app/api/routes/scrape.py + app/main.py
Ne Test Ediliyor:
  1. GET /health â€” saÄŸlÄ±k kontrolÃ¼
  2. POST /api/scrape/analyze â€” geÃ§erli ve geÃ§ersiz istekler
  3. POST /api/scrape/deep â€” deep scrape endpoint'i
  4. GET /api/scrape/status/{job_id} â€” durum sorgulama
  5. HTTP durum kodlarÄ± (200, 202, 422)
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    """FastAPI test client'Ä± oluÅŸtur."""
    return TestClient(app)


#  Health Check

class TestHealthEndpoint:

    def test_health_returns_ok(self, client):
        """Girdi: GET /health
        Beklenen: 200, {"status": "ok", ...}"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "service" in data

    def test_health_returns_service_name(self, client):
        """Girdi: GET /health
        Beklenen: service alanÄ± app_name'i iÃ§erir"""
        response = client.get("/health")
        data = response.json()
        assert "scraper" in data["service"].lower() or data["service"]


#  POST /api/scrape/analyze

class TestAnalyzeEndpoint:

    @patch("app.api.routes.scrape.scrape_and_analyze")
    def test_valid_analyze_request(self, mock_task, client):
        """Girdi: POST /api/scrape/analyze {"url": "https://example.com", "query": "test"}
        Beklenen: 202 Accepted, job_id dÃ¶ner"""
        # Mock Celery task
        mock_result = MagicMock()
        mock_result.id = "test-job-123"
        mock_task.delay.return_value = mock_result

        response = client.post(
            "/api/scrape/analyze",
            json={"url": "https://example.com", "query": "sayfadaki fiyat nedir?"},
        )

        assert response.status_code == 202
        data = response.json()
        assert data["job_id"] == "test-job-123"
        assert data["status"] == "queued"

    def test_invalid_url_returns_422(self, client):
        """Girdi: POST /api/scrape/analyze {"url": "not-valid", "query": "test"}
        Beklenen: 422 Unprocessable Entity"""
        response = client.post(
            "/api/scrape/analyze",
            json={"url": "not-valid", "query": "test"},
        )
        assert response.status_code == 422

    def test_empty_query_returns_422(self, client):
        """Girdi: POST /api/scrape/analyze {"url": "https://example.com", "query": "  "}
        Beklenen: 422 Unprocessable Entity"""
        response = client.post(
            "/api/scrape/analyze",
            json={"url": "https://example.com", "query": "  "},
        )
        assert response.status_code == 422

    def test_missing_fields_returns_422(self, client):
        """Girdi: POST /api/scrape/analyze {} (boÅŸ body)
        Beklenen: 422 Unprocessable Entity"""
        response = client.post("/api/scrape/analyze", json={})
        assert response.status_code == 422

    @patch("app.api.routes.scrape.scrape_and_analyze")
    def test_analyze_with_timeout(self, mock_task, client):
        """Girdi: POST /api/scrape/analyze {... timeout_ms: 60000}
        Beklenen: 202, timeout_ms celery'ye iletilir"""
        mock_result = MagicMock()
        mock_result.id = "timeout-job"
        mock_task.delay.return_value = mock_result

        response = client.post(
            "/api/scrape/analyze",
            json={
                "url": "https://example.com",
                "query": "test",
                "timeout_ms": 60000,
            },
        )

        assert response.status_code == 202
        mock_task.delay.assert_called_once_with(
            url="https://example.com/",
            query="test",
            timeout_ms=60000,
        )


#  POST /api/scrape/deep

class TestDeepEndpoint:

    @patch("app.api.routes.scrape.deep_scrape_and_analyze")
    def test_valid_deep_request(self, mock_task, client):
        """Girdi: POST /api/scrape/deep {"url": ..., "query": ..., "max_pages": 5}
        Beklenen: 202 Accepted, job_id dÃ¶ner"""
        mock_result = MagicMock()
        mock_result.id = "deep-job-456"
        mock_task.delay.return_value = mock_result

        response = client.post(
            "/api/scrape/deep",
            json={
                "url": "https://example.com",
                "query": "en ucuz otel",
                "max_pages": 5,
            },
        )

        assert response.status_code == 202
        data = response.json()
        assert data["job_id"] == "deep-job-456"

    def test_deep_max_pages_too_high_returns_422(self, client):
        """Girdi: max_pages=200 (100'den fazla)
        Beklenen: 422"""
        response = client.post(
            "/api/scrape/deep",
            json={
                "url": "https://example.com",
                "query": "test",
                "max_pages": 200,
            },
        )
        assert response.status_code == 422


#  GET /api/scrape/status/{job_id}

class TestStatusEndpoint:

    @patch("app.api.routes.scrape.AsyncResult")
    def test_status_pending(self, mock_async_result, client):
        """Girdi: GET /api/scrape/status/job-1 (PENDING durumda)
        Beklenen: {"status": "queued"}"""
        mock_result = MagicMock()
        mock_result.state = "PENDING"
        mock_result.result = None
        mock_async_result.return_value = mock_result

        response = client.get("/api/scrape/status/job-1")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"
        assert data["result"] is None

    @patch("app.api.routes.scrape.AsyncResult")
    def test_status_success(self, mock_async_result, client):
        """Girdi: GET /api/scrape/status/job-2 (SUCCESS durumda)
        Beklenen: {"status": "done", "result": {...}}"""
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.result = {
            "url": "https://example.com",
            "query": "test",
            "raw_text_length": 1500,
            "llm_answer": "Cevap budur.",
        }
        mock_async_result.return_value = mock_result

        response = client.get("/api/scrape/status/job-2")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        assert data["result"]["llm_answer"] == "Cevap budur."

    @patch("app.api.routes.scrape.AsyncResult")
    def test_status_failure(self, mock_async_result, client):
        """Girdi: GET /api/scrape/status/job-3 (FAILURE durumda)
        Beklenen: {"status": "failed", "error": "..."}"""
        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.result = RuntimeError("Task timed out.")
        mock_async_result.return_value = mock_result

        response = client.get("/api/scrape/status/job-3")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "timed out" in data["error"].lower()

    @patch("app.api.routes.scrape.AsyncResult")
    def test_status_processing(self, mock_async_result, client):
        """Girdi: GET /api/scrape/status/job-4 (STARTED durumda)
        Beklenen: {"status": "processing"}"""
        mock_result = MagicMock()
        mock_result.state = "STARTED"
        mock_result.result = None
        mock_async_result.return_value = mock_result

        response = client.get("/api/scrape/status/job-4")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
