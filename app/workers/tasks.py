"""
app/workers/tasks.py
Celery task definitions.
"""
import asyncio
import logging

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.schemas import ScrapeResult, DeepScrapeResult
from app.services.llm_service import LLMService
from app.services.scraper_service import ScraperService
from app.services.deep_scraper_service import DeepScraperService
from app.workers.celery_app import celery_app


def _run(coro):
    """
    Run an async coroutine from a synchronous Celery task.

    asyncio.run() yerine yeni bir event loop oluÅŸturuyoruz â€” Celery worker'larÄ±
    bazen Ã¶nceki task'tan kalan loop'u miras alÄ±r ve bu Python 3.12'de hata verir.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Tek sayfa scraping

@celery_app.task(
    bind=True,
    name="tasks.scrape_and_analyze",
    max_retries=2,
    default_retry_delay=10,
    soft_time_limit=300,   # 5 dakika â€” SoftTimeLimitExceeded raise eder
    time_limit=360,        # 6 dakika â€” SIGKILL
)
def scrape_and_analyze(
    self: Task,
    url: str,
    query: str,
    timeout_ms: int | None = None,
) -> dict:
    settings = get_settings()
    logger: logging.Logger = get_logger(__name__)

    scraper = ScraperService(settings=settings, logger=logger)
    llm     = LLMService(settings=settings, logger=logger)

    logger.info("Task started | job_id=%s url=%s query=%.80s",
                self.request.id, url, query)

    try:
        content = _run(scraper.scrape(url=url, timeout_ms=timeout_ms))
        answer  = _run(llm.analyze(content=content, query=query))
        result  = ScrapeResult(
            url=url, query=query,
            raw_text_length=len(content), llm_answer=answer,
        )
        logger.info("Task completed | job_id=%s", self.request.id)
        return result.model_dump()

    except SoftTimeLimitExceeded as exc:
        logger.error("Task soft limit exceeded | job_id=%s", self.request.id)
        raise RuntimeError("Task timed out (soft limit).") from exc

    except RuntimeError as exc:
        err_str = str(exc)
        # Rate limit hatalarÄ±nda daha uzun bekle (exponential backoff)
        if "rate limit" in err_str.lower() or "429" in err_str:
            countdown = 60 * (self.request.retries + 1)  # 60s, 120s
            logger.warning(
                "Rate limit hit, retrying in %ds | job_id=%s attempt=%d",
                countdown, self.request.id, self.request.retries,
            )
            raise self.retry(exc=exc, countdown=countdown)

        logger.warning("Task failed, retrying | job_id=%s attempt=%d error=%s",
                       self.request.id, self.request.retries, err_str)
        raise self.retry(exc=exc)


# Ã‡oklu sayfa (deep) scraping

@celery_app.task(
    bind=True,
    name="tasks.deep_scrape_and_analyze",
    max_retries=1,
    default_retry_delay=15,
    soft_time_limit=600,   # 10 dakika
    time_limit=720,        # 12 dakika
)
def deep_scrape_and_analyze(
    self: Task,
    url: str,
    query: str,
    link_pattern: str | None = None,
    max_pages: int = 30,
    timeout_ms: int | None = None,
) -> dict:
    """
    Ã‡oklu sayfa scraping task'Ä±:
      1. BaÅŸlangÄ±Ã§ URL'sindeki linkleri toplar
      2. Her alt sayfayÄ± ziyaret eder
      3. TÃ¼m iÃ§erikleri LLM'e gÃ¶nderir
    """
    settings = get_settings()
    logger: logging.Logger = get_logger(__name__)

    deep_scraper = DeepScraperService(settings=settings, logger=logger)
    llm          = LLMService(settings=settings, logger=logger)

    logger.info(
        "DeepTask started | job_id=%s url=%s pattern=%s max_pages=%d",
        self.request.id, url, link_pattern, max_pages,
    )

    try:
        scrape_result = _run(deep_scraper.deep_scrape(
            url=url,
            query=query,
            link_pattern=link_pattern,
            max_pages=max_pages,
            timeout_ms=timeout_ms,
        ))

        combined_text = scrape_result["combined_text"]
        total_pages   = scrape_result["total_pages"]

        logger.info("DeepScrape done | pages=%d chars=%d | sending to LLM",
                    total_pages, len(combined_text))

        answer = _run(llm.analyze(content=combined_text, query=query))

        result = DeepScrapeResult(
            index_url=url,
            query=query,
            total_pages_visited=total_pages,
            combined_text_length=len(combined_text),
            llm_answer=answer,
        )
        logger.info("DeepTask completed | job_id=%s", self.request.id)
        return result.model_dump()

    except SoftTimeLimitExceeded as exc:
        logger.error("DeepTask soft limit exceeded | job_id=%s", self.request.id)
        raise RuntimeError("Deep scrape timed out.") from exc

    except RuntimeError as exc:
        err_str = str(exc)
        if "rate limit" in err_str.lower() or "429" in err_str:
            countdown = 90 * (self.request.retries + 1)
            logger.warning(
                "Rate limit hit, retrying in %ds | job_id=%s",
                countdown, self.request.id,
            )
            raise self.retry(exc=exc, countdown=countdown)

        logger.warning("DeepTask failed | job_id=%s error=%s",
                       self.request.id, err_str)
        raise self.retry(exc=exc)
