from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from liyan_server.crawl4ai_adapter import Crawl4AiUrlFetcher
from liyan_server.database import Database, Execution
from liyan_server.file_parse_worker import process_file_parse
from liyan_server.file_parsing import FileParseLimits
from liyan_server.object_storage import R2ObjectStorage
from liyan_server.settings import Settings
from liyan_server.url_fetch_worker import process_url_fetch

settings = Settings()
celery_app = Celery("liyan-worker", broker=settings.broker_url)


@celery_app.task(name="liyan.process_execution")  # type: ignore[untyped-decorator]
def process_execution(execution_id: str) -> None:
    parsed_id = UUID(execution_id)
    database = Database(settings.database_url)
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    try:
        with Session(database.engine) as session:
            execution = session.get(Execution, parsed_id)
            operation = execution.operation if execution else None
    finally:
        database.dispose()
    if operation == "fetch_url":
        fetch_url_execution(execution_id)
    elif operation == "parse_file":
        process_file_parse(
            settings.database_url,
            parsed_id,
            R2ObjectStorage(settings),
            limits=FileParseLimits(
                max_pages=settings.file_max_pages,
                max_normalized_characters=settings.file_max_normalized_characters,
                timeout_seconds=settings.file_parse_timeout_seconds,
                max_docx_entries=settings.file_max_docx_entries,
                max_docx_uncompressed_bytes=settings.file_max_docx_uncompressed_bytes,
            ),
            short_source_characters=settings.short_source_characters,
        )


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
