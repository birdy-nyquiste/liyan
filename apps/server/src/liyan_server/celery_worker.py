from datetime import UTC, datetime
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from liyan_server.cleanup import policy_from, run_cleanup
from liyan_server.crawl4ai_adapter import Crawl4AiUrlFetcher
from liyan_server.credit_reconciliation import reconcile_settlements
from liyan_server.database import Database, Execution, share_engine
from liyan_server.execution_dispatch import (
    PROVIDER_QUEUE,
    SCHEDULED_QUEUE,
    SOURCE_QUEUE,
    CeleryExecutionDispatcher,
)
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
from liyan_server.worker_health import BEAT_WORKER, forget_retired_workers, record_heartbeat
from liyan_server.zhiyan.deepseek import DeepSeekZhiyanProvider
from liyan_server.zhiyan.worker import process_zhiyan_run

configure_logging()
settings = Settings()
celery_app = Celery("liyan-worker", broker=settings.broker_url)

# Where anything unrouted lands. Both worker services name their queue with
# `-Q`, so this only decides for a task nobody routed — and the heavy queue is
# the conservative place for that to be. Left to Celery's own default the
# worker would listen on `celery` while every Execution piled up elsewhere, and
# nothing would say so.
celery_app.conf.task_default_queue = SOURCE_QUEUE

# One engine for this process, sized to how many tasks it runs at once.
#
# Without it each task builds its own pool, and the provider worker's threads
# would hold `concurrency` pools of up to fifteen connections against one small
# Postgres. That fails as intermittent connection exhaustion under load, which
# reads as a database problem rather than a pool-sizing one — so this lands with
# the thread pool, never after it.
#
# A little over concurrency: a task briefly holds two sessions when it settles a
# 预扣 while writing a cost.
share_engine(settings.database_url, pool_size=settings.worker_concurrency + 2)

# Celery replaces the root logger's handlers when a worker starts, which threw
# away the JSON formatter and every `extra` field with it: `execution_failed`
# reached the logs carrying no operation, no error code, and no execution id —
# the exact fields it exists to carry. Keeping our own handlers is the whole
# point of having configured them.
celery_app.conf.worker_hijack_root_logger = False
# Same reasoning for stdout: a print or a library's stray write should go
# through the formatter rather than around it.
celery_app.conf.worker_redirect_stdouts = False

#: Cleanup is the one job nobody triggers, which is why it needs a schedule at
#: all. Beat is a separate process from the worker: without it nothing is ever
#: collected, and nothing says so.
celery_app.conf.beat_schedule = {
    "clean-expired-data": {
        "task": "liyan.clean_expired_data",
        "schedule": float(settings.cleanup_interval_seconds),
        # Database and R2 work. The heavy queue's single slot is far too scarce
        # to spend on a sweep, and a sweep queued behind a 10MB PDF is a sweep
        # that does not run.
        "options": {"queue": SCHEDULED_QUEUE},
    },
    "recover-stalled-executions": {
        "task": "liyan.recover_stalled_executions",
        "schedule": float(settings.stalled_sweep_interval_seconds),
        "options": {"queue": SCHEDULED_QUEUE},
    },
    # One ping per queue, so a heartbeat stops being a function of demand.
    #
    # `record_heartbeat` is written on the way into each run — "a worker that is
    # processing is by definition alive" — which worked while one worker did
    # everything and was rarely idle. Split in two, `source-processing` will
    # genuinely idle for hours, especially now that a user who has never paid
    # cannot enqueue heavy work at all, and a perfectly healthy worker would
    # report `silent`. So beat gives each queue something to do.
    "ping-source-queue": {
        "task": "liyan.ping",
        "schedule": float(settings.stalled_sweep_interval_seconds),
        "options": {"queue": SOURCE_QUEUE},
    },
    "ping-provider-queue": {
        "task": "liyan.ping",
        "schedule": float(settings.stalled_sweep_interval_seconds),
        "options": {"queue": PROVIDER_QUEUE},
    },
}


def record_scheduled_heartbeat() -> None:
    """Say that both processes a scheduled task depends on were alive just now.

    This worker, because it is running this. And beat, because only beat sends
    a scheduled task — so one arriving is the only evidence beat exists.

    Both, not one. Writing only `worker_name` leaves no `liyan-beat` row for
    anything to go stale, and a dead beat then hides behind the worker's own
    heartbeat: the API answers, the worker runs, readiness says `beating`, and
    nothing is ever cleaned up or recovered again. Writing only `BEAT_WORKER`
    has the opposite hole — a worker with no user work would fall silent
    between sweeps, which is the state these sweeps run in most of the time.
    """
    record_heartbeat(settings.database_url, settings.worker_name)
    record_heartbeat(settings.database_url, BEAT_WORKER)


@celery_app.task(name="liyan.ping")  # type: ignore[untyped-decorator]
def ping() -> None:
    """Do nothing, visibly.

    Whichever worker consumes this says so under its own name, which is the
    whole point: it proves that queue has a live consumer whether or not any
    user has asked for anything. Nothing else here can prove that — an empty
    queue and an abandoned one look identical from the outside.
    """
    record_scheduled_heartbeat()


@celery_app.task(name="liyan.clean_expired_data")  # type: ignore[untyped-decorator]
def clean_expired_data() -> None:
    record_scheduled_heartbeat()
    # A worker that is gone rather than unwell. Renaming or removing one leaves
    # a heartbeat row that can never beat again, and `worker_state` takes the
    # worst of every row — so readiness would report `silent` forever, naming a
    # process that no longer exists. Splitting one worker into two is exactly
    # that event.
    forget_retired_workers(settings.database_url)
    run_cleanup(
        settings.database_url,
        R2ObjectStorage(settings),
        policy=policy_from(settings),
        now=datetime.now(UTC),
    )


@celery_app.task(name="liyan.recover_stalled_executions")  # type: ignore[untyped-decorator]
def recover_stalled() -> None:
    record_scheduled_heartbeat()
    # After the sweep, not before: a run this pass has just given up on is one
    # whose 预扣 is now settleable, and waiting a whole interval to hand it back
    # would leave a user's 额度 short for no reason they could see.
    recover_stalled_executions(
        settings.database_url,
        policy=stalled_policy_from(settings),
        now=datetime.now(UTC),
    )
    reconcile_settlements(settings.database_url)


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
