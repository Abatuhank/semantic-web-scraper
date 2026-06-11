"""
app/main.py
FastAPI application factory.

Responsibilities:
  - Assemble the app with metadata and middleware.
  - Register all routers.
  - Expose a health-check endpoint.

This module intentionally contains no business logic (SRP).
"""
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import scrape as scrape_router
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger   = get_logger(__name__)


# Lifespan

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown hooks."""
    logger.info(
        "Starting %s | env=%s | log_level=%s",
        settings.app_name, settings.app_env, settings.log_level,
    )
    yield
    logger.info("Shutting down %s", settings.app_name)


# Application factory

def create_app() -> FastAPI:
    app = FastAPI(
        title="Semantic Web Scraper API",
        description=(
            "Submit a URL and a natural-language query. "
            "The system scrapes the page with Playwright and answers your "
            "question using an LLM â€” all asynchronously via Celery + Redis."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # tighten in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(scrape_router.router)

    # Built-in endpoints
    @app.get("/health", tags=["Meta"], summary="Health check")
    async def health() -> dict:
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()
