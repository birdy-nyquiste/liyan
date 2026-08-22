from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]

from liyan_server.crawl4ai_adapter import Crawl4AiUrlFetcher
from liyan_server.settings import Settings
from liyan_server.url_fetch_worker import process_url_fetch

settings = Settings()
celery_app = Celery("liyan-worker", broker=settings.broker_url)


@celery_app.task(name="liyan.fetch_url")  # type: ignore[untyped-decorator]
def fetch_url_execution(execution_id: str) -> None:
    process_url_fetch(
        settings.database_url,
        UUID(execution_id),
        Crawl4AiUrlFetcher(
            base_directory=settings.crawl4ai_base_directory,
            page_timeout_ms=settings.url_fetch_timeout_seconds * 1000,
        ),
        short_source_characters=settings.short_source_characters,
    )
