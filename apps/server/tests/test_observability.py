"""What a log line may say, and what it may never say.

Logs leave the machine and are read by people and by services. 立言阁 handles
source bodies, 知言报告, user instructions, articles, and Blog credentials, and
none of those belong in a log at any level. The rule here is an allowlist rather
than a list of forbidden words: a key nobody has vouched for is dropped, so the
next field somebody adds cannot leak by being unanticipated.
"""

import json
import logging
import sys
from typing import Any

from liyan_server.observability import (
    UVICORN_LOGGERS,
    JsonLogFormatter,
    configure_logging,
)


def _emitted(message: str, **extra: Any) -> dict[str, Any]:
    record = logging.LogRecord(
        name="liyan_server.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    parsed: dict[str, Any] = json.loads(JsonLogFormatter().format(record))
    return parsed


def test_a_line_is_one_json_object_naming_the_event_and_its_level() -> None:
    line = _emitted("zhiyan_run_finished")

    assert line["message"] == "zhiyan_run_finished"
    assert line["level"] == "INFO"
    assert line["logger"] == "liyan_server.test"
    assert "timestamp" in line


def test_the_identities_an_operator_needs_survive() -> None:
    """Without these a log line cannot be joined to anything it describes."""
    line = _emitted(
        "zhiyan_run_finished",
        trace_id="trace-1",
        execution_id="execution-1",
        task_id="task-1",
        owner_id="owner-1",
        operation="analyze_source",
        attempt=2,
        error_code="provider_unavailable",
    )

    assert line["trace_id"] == "trace-1"
    assert line["execution_id"] == "execution-1"
    assert line["task_id"] == "task-1"
    assert line["owner_id"] == "owner-1"
    assert line["operation"] == "analyze_source"
    assert line["attempt"] == 2
    assert line["error_code"] == "provider_unavailable"


def test_business_content_never_reaches_a_log_line() -> None:
    line = _emitted(
        "zhiyan_run_finished",
        body="来源正文，绝不该出现在日志里。",
        report={"overview": {"content_summary": "秘密"}},
        instruction="用户写的生成指令",
        body_markdown="# 文章正文",
        title="文章标题",
    )

    rendered = json.dumps(line, ensure_ascii=False)
    for secret in ("来源正文", "秘密", "用户写的生成指令", "文章正文", "文章标题"):
        assert secret not in rendered
    # Dropping in silence would hide a mistake; the names alone are safe to say.
    assert set(line["dropped_fields"]) == {
        "body",
        "report",
        "instruction",
        "body_markdown",
        "title",
    }


def test_credentials_and_authorization_never_reach_a_log_line() -> None:
    line = _emitted(
        "request_finished",
        authorization="Bearer supabase-access-token",
        blog_ingest_token="ingest-secret",
        password="hunter2",
        otp="123456",
        r2_secret_access_key="r2-secret",
    )

    rendered = json.dumps(line, ensure_ascii=False)
    for secret in ("supabase-access-token", "ingest-secret", "hunter2", "123456", "r2-secret"):
        assert secret not in rendered


def test_an_unrecognised_field_is_dropped_rather_than_guessed_at() -> None:
    """The rule that makes the next field safe before anyone reviews it."""
    line = _emitted("something_new", some_future_field="possibly sensitive")

    assert "some_future_field" not in line
    assert "possibly sensitive" not in json.dumps(line)
    assert line["dropped_fields"] == ["some_future_field"]


def test_an_exception_is_reported_by_type_alone() -> None:
    """An exception string routinely quotes whatever it was handed."""
    try:
        raise ValueError("Blog rejected the body: 来源正文")
    except ValueError:
        record = logging.LogRecord(
            name="liyan_server.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="publication_failed",
            args=(),
            exc_info=sys.exc_info(),
        )
        line = json.loads(JsonLogFormatter().format(record))

    assert line["exception"] == "ValueError"
    assert "来源正文" not in json.dumps(line, ensure_ascii=False)


def test_configuring_logging_twice_leaves_one_handler() -> None:
    """Both entry points configure at import, and tests import both."""
    configure_logging()
    configure_logging()

    root = logging.getLogger()
    assert len([h for h in root.handlers if isinstance(h.formatter, JsonLogFormatter)]) == 1


def test_uvicorns_own_handlers_are_taken_over() -> None:
    """Its access line carries the raw request target, query string included.

    Uvicorn installs these before the application is imported and they do not
    propagate, so without this they would bypass every rule in this module.
    """
    for name in UVICORN_LOGGERS:
        noisy = logging.getLogger(name)
        noisy.handlers = [logging.StreamHandler()]
        noisy.propagate = False

    configure_logging()

    for name in UVICORN_LOGGERS:
        reclaimed = logging.getLogger(name)
        assert reclaimed.handlers == []
        assert reclaimed.propagate is True
