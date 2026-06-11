"""
app/models/schemas.py
All Pydantic models (request payloads, API responses).
Keeping them in one place makes the contract easy to audit and swap.
"""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, HttpUrl, field_validator


# Enumerations

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


# Request Models

class ScrapeRequest(BaseModel):
    """Payload for POST /api/scrape/analyze."""

    url: HttpUrl
    query: str
    timeout_ms: Optional[int] = None   # falls back to SCRAPER_DEFAULT_TIMEOUT_MS

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        return v

    @field_validator("timeout_ms", mode="before")
    @classmethod
    def validate_timeout(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        v = int(v)
        if v <= 0:
            return None  # 0 veya negatif â†’ default kullan
        if v > 120_000:
            raise ValueError("timeout_ms cannot exceed 120000 (2 minutes)")
        return v


# Response Models

class ScrapeJobResponse(BaseModel):
    """Returned immediately after a job is enqueued."""

    job_id: str
    status: JobStatus = JobStatus.QUEUED
    message: str = "Job enqueued. Poll /api/scrape/status/{job_id} for results."


class JobStatusResponse(BaseModel):
    """Returned by GET /api/scrape/status/{job_id}."""

    job_id: str
    status: JobStatus
    result: Optional[Any] = None    # filled when status == DONE
    error: Optional[str] = None     # filled when status == FAILED


class ScrapeResult(BaseModel):
    """Stored inside Celery result backend on success."""

    url: str
    query: str
    raw_text_length: int
    llm_answer: str


# Deep (multi-page) scraping models

class DeepScrapeRequest(BaseModel):
    """Payload for POST /api/scrape/deep â€” Ã§oklu sayfa tarama."""

    url: HttpUrl
    query: str
    link_pattern: Optional[str] = None   # Ã–rn: "lisans.php" â€” sadece bu linkleri takip et
    max_pages: int = 10                   # Default 10 â€” daha makul baÅŸlangÄ±Ã§ deÄŸeri
    timeout_ms: Optional[int] = None

    @field_validator("query")
    @classmethod
    def query_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        return v

    @field_validator("link_pattern", mode="before")
    @classmethod
    def sanitize_link_pattern(cls, v: Optional[str]) -> Optional[str]:
        """Swagger default deÄŸeri 'string'i None'a Ã§evir."""
        if v is None:
            return None
        v = v.strip()
        # Swagger'Ä±n default placeholder'Ä± veya anlamsÄ±z kÄ±sa deÄŸerleri temizle
        if v.lower() in ("string", "", "null", "none"):
            return None
        return v

    @field_validator("max_pages")
    @classmethod
    def max_pages_limit(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("max_pages must be between 1 and 100")
        return v

    @field_validator("timeout_ms", mode="before")
    @classmethod
    def validate_timeout(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        v = int(v)
        if v <= 0:
            return None
        if v > 120_000:
            raise ValueError("timeout_ms cannot exceed 120000 (2 minutes)")
        return v


class DeepScrapeResult(BaseModel):
    """Stored inside Celery result backend on deep scrape success."""

    index_url: str
    query: str
    total_pages_visited: int
    combined_text_length: int
    llm_answer: str
