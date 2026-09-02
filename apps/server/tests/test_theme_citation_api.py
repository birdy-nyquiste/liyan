"""Citing a 主题知言报告 in a 立言指令 — the only way it reaches an article.

The 主题 report gates 立言 but does not enter it: it is reference reading, and
material the Agent found on its own must not arrive in an article the user did
not ask to put it in. So the two things proved here are the two halves of that
decision — the report is absent from the default context, and a 胶囊 the user
placed brings exactly one item of it in.
"""

from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session
from zhiyan_support import (
    DEFAULT_THEME,
    confirm_sources,
    theme_report_document,
    zhiyan_client,
)

from liyan_server.database import Database, Task, ThemeReport

SOURCES = ["四天工作制已经没有争议", "小企业为什么害怕四天工作制"]


def theme_capsule(
    dispatcher_url: str,
    task_id: str,
    item_id: str = "TB-01",
) -> dict[str, str]:
    database = Database(dispatcher_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        task = session.get(Task, UUID(task_id))
        assert task is not None and task.current_version_id is not None
        report = session.query(ThemeReport).filter_by(owner_id=task.owner_id).first()
        assert report is not None
        capsule = {
            "type": "capsule",
            "task_version_id": str(task.current_version_id),
            "report_id": str(report.id),
            "item_id": item_id,
            "report_kind": "theme",
        }
    database.dispose()
    return capsule


def test_a_theme_report_does_not_enter_the_default_liyan_context(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1], theme=DEFAULT_THEME)
    dispatcher.run_all()

    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "no-theme-context", "instruction": {"content": []}},
    )
    assert started.status_code == 202, started.text
    dispatcher.run_all()

    request = dispatcher.liyan_provider.requests[-1]
    blind_spot = theme_report_document()["blind_spots"]["items"][0]["angle"]
    assert blind_spot not in request.input_text
    # The 主题 text itself is not smuggled in either: what the article is written
    # from is the 来源 and their reports.
    assert DEFAULT_THEME not in request.input_text


def test_a_theme_capsule_brings_one_item_into_the_instruction(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1], theme=DEFAULT_THEME)
    dispatcher.run_all()
    capsule = theme_capsule(dispatcher.database_url, task_id)

    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={
            "idempotency_key": "theme-capsule",
            "instruction": {
                "content": [
                    {"type": "text", "text": "补上这一节被忽略的角度："},
                    capsule,
                ]
            },
        },
    )

    assert started.status_code == 202, started.text
    dispatcher.run_all()
    request = dispatcher.liyan_provider.requests[-1]
    assert '"capsule": 1' in request.input_text
    assert '"kind": "theme_blind_spot"' in request.input_text
    assert "班次制行业的排班成本" in request.input_text
    # Nothing else of the report travels — one 胶囊 is one item.
    assert "参与英国试验的企业以知识工作为主" not in request.input_text
    assert "theme_" in request.instructions


def test_a_theme_capsule_from_another_version_is_refused(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1], theme=DEFAULT_THEME)
    dispatcher.run_all()
    capsule = theme_capsule(dispatcher.database_url, task_id)

    forged = dict(capsule)
    forged["task_version_id"] = str(UUID(int=0))
    refused = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={
            "idempotency_key": "forged-theme-capsule",
            "instruction": {"content": [forged]},
        },
    )

    assert refused.status_code == 422
    assert "无效或过期" in refused.json()["detail"]


def test_a_theme_capsule_naming_a_source_report_id_is_refused(tmp_path: Path) -> None:
    """The kind decides which table is read, so the two cannot be crossed."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1], theme=DEFAULT_THEME)
    dispatcher.run_all()
    capsule = theme_capsule(dispatcher.database_url, task_id)

    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        from liyan_server.database import ZhiyanReport

        source_report = session.query(ZhiyanReport).first()
        assert source_report is not None
        crossed = dict(capsule) | {"report_id": str(source_report.id)}
    database.dispose()

    refused = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "crossed-capsule", "instruction": {"content": [crossed]}},
    )

    assert refused.status_code == 422


def test_an_item_id_that_is_not_in_the_theme_report_is_refused(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1], theme=DEFAULT_THEME)
    dispatcher.run_all()
    capsule = theme_capsule(dispatcher.database_url, task_id, item_id="TB-99")

    refused = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "missing-item", "instruction": {"content": [capsule]}},
    )

    assert refused.status_code == 422


def test_a_source_capsule_still_resolves_without_naming_its_kind(tmp_path: Path) -> None:
    """An instruction recorded before 主题 existed keeps working unchanged."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1], theme=DEFAULT_THEME)
    dispatcher.run_all()
    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        from liyan_server.database import ZhiyanReport

        task = session.get(Task, UUID(task_id))
        assert task is not None and task.current_version_id is not None
        report = session.query(ZhiyanReport).first()
        assert report is not None
        legacy = {
            "type": "capsule",
            "task_version_id": str(task.current_version_id),
            "report_id": str(report.id),
            "item_id": "F-01",
        }
    database.dispose()

    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "legacy-capsule", "instruction": {"content": [legacy]}},
    )

    assert started.status_code == 202, started.text
    dispatcher.run_all()
    assert '"kind": "fact"' in dispatcher.liyan_provider.requests[-1].input_text


def test_liyan_is_refused_outright_while_the_theme_report_is_missing(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1], theme=DEFAULT_THEME)
    # Run only the 来源 analysis; the 主题 run stays queued.
    dispatcher.run_next()

    refused = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "too-early", "instruction": {"content": []}},
    )

    assert refused.status_code == 409
    state = client.get(f"/tasks/{task_id}/liyan", headers=headers).json()
    assert state["capabilities"]["can_generate"] is False
