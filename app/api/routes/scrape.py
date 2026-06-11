"""
app/api/routes/scrape.py
REST endpoints for the scraping workflow.

Endpoints
POST /api/scrape/analyze     â†’ Tek sayfa scrape + LLM analiz
POST /api/scrape/deep        â†’ Ã‡oklu sayfa deep scrape + LLM analiz
GET  /api/scrape/status/{id} â†’ Job durumu ve sonucu
"""
from typing import Optional

from celery.result import AsyncResult
from fastapi import APIRouter, status

from app.models.schemas import (
    DeepScrapeRequest,
    JobStatus,
    JobStatusResponse,
    ScrapeJobResponse,
    ScrapeRequest,
)
from app.workers.tasks import deep_scrape_and_analyze, scrape_and_analyze

router = APIRouter(prefix="/api/scrape", tags=["Scraping"])


def _state_to_status(state: str) -> JobStatus:
    return {
        "PENDING":  JobStatus.QUEUED,
        "RECEIVED": JobStatus.QUEUED,
        "STARTED":  JobStatus.PROCESSING,
        "RETRY":    JobStatus.PROCESSING,
        "SUCCESS":  JobStatus.DONE,
        "FAILURE":  JobStatus.FAILED,
        "REVOKED":  JobStatus.FAILED,
    }.get(state, JobStatus.PROCESSING)


def _build_status_response(job_id: str, task_result: AsyncResult) -> JobStatusResponse:
    job_status = _state_to_status(task_result.state)
    return JobStatusResponse(
        job_id=job_id,
        status=job_status,
        result=task_result.result if job_status == JobStatus.DONE else None,
        error=str(task_result.result) if job_status == JobStatus.FAILED else None,
    )


# Tek sayfa

@router.post(
    "/analyze",
    response_model=ScrapeJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Tek sayfayÄ± scrape et ve analiz et",
    description=(
        "URL ve doÄŸal dil sorgusu alÄ±r. "
        "`job_id` dÃ¶ner â€” `/api/scrape/status/{job_id}` ile sonucu takip et."
    ),
)
async def analyze(payload: ScrapeRequest) -> ScrapeJobResponse:
    task = scrape_and_analyze.delay(
        url=str(payload.url),
        query=payload.query,
        timeout_ms=payload.timeout_ms,
    )
    return ScrapeJobResponse(job_id=task.id)


# Ã‡oklu sayfa (deep)

@router.post(
    "/deep",
    response_model=ScrapeJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ã‡oklu sayfa deep scrape + LLM analiz",
    description=(
        "Liste sayfasÄ±ndaki linkleri takip ederek tÃ¼m alt sayfalarÄ± scrape eder. "
        "YÃ–K Atlas gibi 'Ã¶nce listeye git, sonra tÄ±kla' gerektiren siteler iÃ§in. "
        "`link_pattern` ile hangi linklerin takip edileceÄŸini filtrele. "
        "Ã–rn: `link_pattern='lisans.php'`"
    ),
)
async def deep_analyze(payload: DeepScrapeRequest) -> ScrapeJobResponse:
    task = deep_scrape_and_analyze.delay(
        url=str(payload.url),
        query=payload.query,
        link_pattern=payload.link_pattern,
        max_pages=payload.max_pages,
        timeout_ms=payload.timeout_ms,
    )
    return ScrapeJobResponse(
        job_id=task.id,
        message=(
            f"Deep scrape job enqueued. "
            f"Will visit up to {payload.max_pages} pages. "
            f"Poll /api/scrape/status/{task.id} for results."
        ),
    )


# Durum sorgulama

@router.get(
    "/status/{job_id}",
    response_model=JobStatusResponse,
    summary="Job durumunu sorgula",
)
async def get_status(job_id: str) -> JobStatusResponse:
    # Her iki task tÃ¼rÃ¼ iÃ§in de aynÄ± AsyncResult mekanizmasÄ± Ã§alÄ±ÅŸÄ±r
    task_result: AsyncResult = AsyncResult(job_id)
    return _build_status_response(job_id, task_result)
