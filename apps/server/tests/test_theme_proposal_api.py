"""提炼主题: one press, three candidates, charged once.

The interface rule this defends is the one a user feels: pressing the button is
the only thing that produces candidates, a 来源 changing does not touch what is
on screen, and nothing about 主题 blocks 创建任务 — an empty 主题 is a legitimate
confirmation.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from zhiyan_support import (
    RecordingDispatcher,
    create_session_sources,
    unavailable,
    zhiyan_client,
)

from liyan_server.database import CreditEntry, Database
from liyan_server.theme.proposal import PROPOSAL_FORMAT_NAME

TITLES = ["四天工作制已经没有争议", "试验数据被反复引用"]


def press(
    client: TestClient,
    headers: dict[str, str],
    *,
    client_session_id: str = "session-1",
) -> Any:
    return client.post(
        "/task-creation/theme-proposals",
        headers=headers,
        json={"client_session_id": client_session_id},
    )


def session_with_sources(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], RecordingDispatcher, list[str]]:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    return client, headers, dispatcher, create_session_sources(client, headers, TITLES)


def test_one_press_returns_three_candidates_each_with_its_reason(tmp_path: Path) -> None:
    client, headers, dispatcher, _ = session_with_sources(tmp_path)

    accepted = press(client, headers)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == "running"
    dispatcher.run_all()

    proposal = client.get(
        f"/task-creation/theme-proposals/{accepted.json()['id']}", headers=headers
    )
    payload = proposal.json()
    assert payload["status"] == "succeeded"
    assert [candidate["theme"] for candidate in payload["candidates"]] == [
        "四天工作制在不同行业的实际效果与代价",
        "四天工作制试验数据被引用时的口径问题",
        "工时政策如何在行业之间产生不同后果",
    ]
    assert all(candidate["why"] for candidate in payload["candidates"])


def test_the_press_reads_every_session_source_and_cannot_search(tmp_path: Path) -> None:
    client, headers, dispatcher, _ = session_with_sources(tmp_path)

    press(client, headers)
    dispatcher.run_all()

    request = next(
        sent for sent in dispatcher.provider.requests if sent.format_name == PROPOSAL_FORMAT_NAME
    )
    assert request.tool_policy.web_search_enabled is False
    for title in TITLES:
        assert title in request.input_text


def test_a_session_with_an_unfinished_source_cannot_be_pressed(tmp_path: Path) -> None:
    """The button is not offered until every 来源 is captured, and refused if asked.

    A press against an incomplete set is a press the user pays for and cannot
    use: the answer would be about material they have not finished adding.
    """
    client, headers, dispatcher = zhiyan_client(tmp_path)
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-url",
            "url": "https://press.example/story",
        },
    )
    assert created.status_code == 201, created.text

    refused = press(client, headers)

    assert refused.status_code == 409
    assert "抓取成功" in refused.json()["detail"]

    # Once the fetch lands, the same press is allowed.
    dispatcher.run_all()
    assert press(client, headers).status_code == 202


def test_an_empty_session_cannot_be_pressed(tmp_path: Path) -> None:
    client, headers, _ = zhiyan_client(tmp_path)

    assert press(client, headers).status_code == 409


def test_a_second_press_while_one_is_running_is_refused(tmp_path: Path) -> None:
    client, headers, _, _ = session_with_sources(tmp_path)

    assert press(client, headers).status_code == 202
    refused = press(client, headers)

    assert refused.status_code == 409
    assert refused.json()["detail"] == "主题提炼正在进行中。"


def test_pressing_again_after_a_source_changed_returns_new_candidates(tmp_path: Path) -> None:
    """A 来源 change does nothing until the user presses again — and then this.

    The previous candidates are not invalidated on the server, because the
    server never showed them: each press is its own row, and the client reads
    the one it just created.
    """
    client, headers, dispatcher, source_ids = session_with_sources(tmp_path)
    first = press(client, headers)
    dispatcher.run_all()

    deleted = client.delete(f"/task-creation/sources/{source_ids[1]}", headers=headers)
    assert deleted.status_code == 204, deleted.text

    second = press(client, headers)
    assert second.status_code == 202
    assert second.json()["id"] != first.json()["id"]
    dispatcher.run_all()

    # The first press's candidates are still readable by id: nothing was erased,
    # it is simply no longer the latest answer.
    kept = client.get(f"/task-creation/theme-proposals/{first.json()['id']}", headers=headers)
    assert kept.json()["status"] == "succeeded"


def test_each_press_is_held_and_settled_on_its_own(tmp_path: Path) -> None:
    client, headers, dispatcher, _ = session_with_sources(tmp_path)

    press(client, headers)
    dispatcher.run_all()
    press(client, headers)
    dispatcher.run_all()

    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        holds = list(
            session.scalars(
                select(CreditEntry).where(
                    CreditEntry.kind == "hold",
                    CreditEntry.target_type == "theme_proposal",
                )
            ).all()
        )
    database.dispose()
    # Two presses, two holds against two different rows. A second press is a
    # second answer the provider was paid for, not another try at the first.
    assert len(holds) == 2
    assert len({hold.target_id for hold in holds}) == 2


def test_a_failed_press_may_simply_be_pressed_again(tmp_path: Path) -> None:
    """Failure is not the disallowed "regenerate": this press produced nothing."""
    client, headers, dispatcher, _ = session_with_sources(tmp_path)
    dispatcher.provider.proposal_outcomes.append(unavailable())

    failed = press(client, headers)
    dispatcher.run_all()
    state = client.get(f"/task-creation/theme-proposals/{failed.json()['id']}", headers=headers)
    assert state.json()["status"] == "failed"
    assert state.json()["candidates"] == []
    # Nothing about the failure is told to the user beyond that it failed.
    assert state.json()["execution"]["error"]["code"] == "busy"

    again = press(client, headers)
    assert again.status_code == 202
    dispatcher.run_all()
    assert client.get(
        f"/task-creation/theme-proposals/{again.json()['id']}", headers=headers
    ).json()["status"] == "succeeded"


def test_candidates_that_are_not_three_usable_lines_are_refused(tmp_path: Path) -> None:
    client, headers, dispatcher, _ = session_with_sources(tmp_path)
    import json as json_module

    from zhiyan_support import accepted_candidates_result

    over_long = json_module.loads(accepted_candidates_result().report_text)
    over_long["candidates"][0]["theme"] = "四" * 81
    dispatcher.provider.proposal_outcomes.append(
        accepted_candidates_result().__class__(
            report_text=json_module.dumps(over_long, ensure_ascii=False),
            search_actions=(),
            model="deepseek-v4-flash",
            response_id="proposal_resp_bad",
        )
    )

    started = press(client, headers)
    dispatcher.run_all()

    state = client.get(f"/task-creation/theme-proposals/{started.json()['id']}", headers=headers)
    assert state.json()["status"] == "failed"
    assert state.json()["candidates"] == []


def test_another_users_proposal_is_not_readable(tmp_path: Path) -> None:
    client, headers, dispatcher, _ = session_with_sources(tmp_path)
    started = press(client, headers)
    dispatcher.run_all()

    denied = client.get(
        f"/task-creation/theme-proposals/{started.json()['id']}",
        headers={"Authorization": "Bearer second-token"},
    )

    assert denied.status_code == 404
