"""
app/workers/celery_app.py
Celery application factory.

Responsibilities (this module only):
  - Create and configure the Celery app instance.
  - Set broker / result-backend from Settings.
  - Define result serialization and TTL.

The actual tasks live in `app.workers.tasks` to respect SRP.
"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "semantic_scraper",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Result TTL keep results for 1 hour
    result_expires=3_600,
    # Retry / ack behaviour
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Prevent infinitely long tasks
    task_soft_time_limit=120,    # SoftTimeLimitExceeded raised at 120 s
    task_time_limit=150,         # SIGKILL at 150 s
)
