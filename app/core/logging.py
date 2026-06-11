"""
app/core/logging.py
Structured logging factory.
Call `get_logger(__name__)` from any module â€” returns a configured Logger
with the log-level from Settings and a consistent format.
"""
import logging
import sys
from functools import lru_cache
from typing import Optional

from app.core.config import get_settings


_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)


def _configure_root_logger() -> None:
    """Set up the root logger once at import time."""
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S"))

    root = logging.getLogger()
    if not root.handlers:           # guard against double-configuration
        root.setLevel(level)
        root.addHandler(handler)


_configure_root_logger()


@lru_cache(maxsize=None)
def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Return a named logger.  Results are cached so repeated calls with the
    same name always return the same instance.

    Usage::
        logger = get_logger(__name__)
        logger.info("Hello from %s", __name__)
    """
    return logging.getLogger(name or "semantic-scraper")
