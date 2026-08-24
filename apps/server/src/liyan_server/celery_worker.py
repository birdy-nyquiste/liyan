from datetime import UTC, datetime
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from liyan_server.cleanup import policy_from, run_cleanup
from liyan_server.crawl4ai_adapter import Crawl4AiUrlFetcher
from liyan_server.database import Database, Execution
from liyan_server.execution_dispatch import EXECUTION_QUEUE, CeleryExecutionDispatcher
from liyan_server.file_parse_worker import process_file_parse
from liyan_server.file_parsing import FileParseLimits
from liyan_server.liyan.deepseek import DeepSeekLiyanProvider
from liyan_server.liyan.worker import process_liyan_run
from liyan_server.object_storage import R2ObjectStorage
from liyan_server.observability import configure_logging
from liyan_server.publication.blog import LsforumBlogSubmitter
from liyan_server.publication.worker import process_publication_run
from liyan_server.settings import Settings
from liyan_server.stalled import policy_from as stalled_policy_from
from liyan_server.stalled import recover_stalled_executions
from liyan_server.url_fetch_worker import process_url_fetch
from liyan_server.worker_health import record_heartbeat
from liyan_server.zhiyan.deepseek import DeepSeekZhiyanProvider
from liyan_server.zhiyan.worker import process_zhiyan_run

configure_logging()
settings = Settings()
celery_app = Celery("liyan-worker", broker=settings.broker_url)

# What this worker consumes, and where beat sends. The API dispatches to the
# same name, so the two cannot disagree without the import failing. Left to
# Celery's default the worker would listen on `celery` while every Execution
# piled up in `source-processing`, and nothing would say so.
celery_app.conf.task_default_queue = EXECUTION_QUEUE

#: Cleanup is the one job nobody triggers, which is why it needs a schedule at
#: all. Beat is a separate process from the worker: without it nothing is ever
#: collected, and nothing says so.
celery_app.conf.beat_schedule = {
    "clean-expired-data": {
        "task": "liyan.clean_expired_data",
        "schedule": float(settings.cleanup_interval_seconds),
    },
    "recover-stalled-executions": {
        "task": "liyan.recover_stalled_executions",
        "schedule": float(settings.stalled_sweep_interval_seconds),
    },
}


@celery_app.task(name="liyan.clean_expired_data")  # type: ignore[untyped-decorator]
def clean_expired_data() -> None:
    # Beat's own heartbeat. Nothing else writes one for it, and a dead beat is
    # invisible: the API answers, the worker runs, and no sweep ever happens.
    record_heartbeat(settings.database_url, settings.worker_name)
    run_cleanup(
        settings.database_url,
        R2ObjectStorage(settings),
        policy=policy_from(settings),
        now=datetime.now(UTC),
    )


@celery_app.task(name="liyan.recover_stalled_executions")  # type: ignore[untyped-decorator]
def recover_stalled() -> None:
    record_heartbeat(settings.database_url, settings.worker_name)
    recover_stalled_executions(
        settings.database_url,
        policy=stalled_policy_from(settings),
        now=datetime.now(UTC),
    )


@celery_app.task(name="liyan.process_execution")  # type: ignore[untyped-decorator]
def process_execution(execution_id: str) -> None:
    # Written before the work, not after: a worker that dies mid-run should
    # still have said it was alive, or its last run would look like its death.
    record_heartbeat(settings.database_url, settings.worker_name)
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
    elif operation == "analyze_source":
        analyze_source_execution(execution_id)
    elif operation == "generate_article":
        generate_article_execution(execution_id)
    elif operation == "publish_preview":
        publish_preview_execution(execution_id)


@celery_app.task(name="liyan.analyze_source")  # type: ignore[untyped-decorator]
def analyze_source_execution(execution_id: str) -> None:
    process_zhiyan_run(
        settings.database_url,
        UUID(execution_id),
        DeepSeekZhiyanProvider(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.zhiyan_timeout_seconds,
        ),
        CeleryExecutionDispatcher(settings.broker_url),
    )


@celery_app.task(name="liyan.generate_article")  # type: ignore[untyped-decorator]
def generate_article_execution(execution_id: str) -> None:
    process_liyan_run(
        settings.database_url,
        UUID(execution_id),
        DeepSeekLiyanProvider(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.liyan_timeout_seconds,
        ),
        CeleryExecutionDispatcher(settings.broker_url),
    )


@celery_app.task(name="liyan.publish_preview")  # type: ignore[untyped-decorator]
def publish_preview_execution(execution_id: str) -> None:
    process_publication_run(
        settings.database_url,
        UUID(execution_id),
        LsforumBlogSubmitter(timeout_seconds=settings.blog_timeout_seconds),
        settings.blog_ingest_token,
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
