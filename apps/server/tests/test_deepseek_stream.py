"""Reading a streamed 知言 call, and what it can say while it is still running.

The adapter streams so that two things become possible that a whole-response
POST cannot offer: a run that reports its searches while it searches, and a
timeout that can tell silence from length. `read_stream` is the part that folds
the event stream back into the response object the rest of the adapter already
knows how to read, so these are the tests that keep the two paths identical.

The frames here are shaped like the live ones, captured from `deepseek-v4-pro`
on 2026-09-12: `response.output_item.done` carries the finished
`web_search_call` with its action, and `response.completed` carries the whole
`response` — `output`, `usage`, `status` and all — which is why nothing
downstream of `read_stream` needed changing.
"""

import json
from typing import Any

from liyan_server.zhiyan.deepseek import _page_key, read_response, read_stream
from liyan_server.zhiyan.provider import SearchAction


def frame(event: dict[str, Any]) -> str:
    return "data: " + json.dumps(event)


def search_done(kind: str, **action: Any) -> str:
    return frame(
        {
            "type": "response.output_item.done",
            "item": {"type": "web_search_call", "action": {"type": kind, **action}},
        }
    )


def completed(response: dict[str, Any]) -> str:
    return frame({"type": "response.completed", "response": response})


FINISHED_RESPONSE: dict[str, Any] = {
    "id": "resp_stream",
    "model": "deepseek-v4-pro",
    "status": "completed",
    "output": [
        {"type": "web_search_call", "action": {"type": "search", "queries": ["四天工作制"]}},
        {"type": "web_search_call", "action": {"type": "open_page", "url": "https://a.example/"}},
        {"type": "message", "content": [{"type": "output_text", "text": '{"overview": "ok"}'}]},
    ],
    "usage": {
        "input_tokens": 1200,
        "input_tokens_details": {"cached_tokens": 1000},
        "output_tokens": 300,
        "output_tokens_details": {"reasoning_tokens": 200},
        "total_tokens": 1500,
    },
}


def test_the_terminal_event_is_the_response_the_adapter_already_reads() -> None:
    """Streaming is a transport detail: the payload is the unstreamed payload."""
    lines = [
        frame({"type": "response.created"}),
        search_done("search", queries=["四天工作制"]),
        completed(FINISHED_RESPONSE),
    ]

    response = read_stream(lines)

    assert response.status_code == 200
    assert response.payload == FINISHED_RESPONSE
    # And the existing reader takes it without knowing where it came from.
    call = read_response(response.payload, fallback_model="deepseek-v4-pro")
    assert call.report_text == '{"overview": "ok"}'
    assert call.usage is not None
    assert call.usage.reasoning_tokens == 200


def test_every_finished_search_is_announced_as_it_lands() -> None:
    announced: list[SearchAction] = []
    lines = [
        search_done("search", queries=["四天工作制"]),
        search_done("open_page", url="https://a.example/#ws_call_id=1"),
        search_done("find_in_page", url="https://b.example/"),
        completed(FINISHED_RESPONSE),
    ]

    read_stream(lines, on_search=announced.append)

    assert [action.kind for action in announced] == ["search", "open_page", "find_in_page"]
    assert announced[1].url == "https://a.example/#ws_call_id=1"


def test_a_search_that_has_only_started_is_not_announced() -> None:
    """`in_progress` and `searching` say a search exists, not that it finished.

    Counting those would make the number jump forward and back as the run's
    parallel searches overlapped, which is worse than counting nothing.
    """
    announced: list[SearchAction] = []
    lines = [
        frame(
            {
                "type": "response.output_item.added",
                "item": {"type": "web_search_call", "action": {"type": "search"}},
            }
        ),
        frame({"type": "response.web_search_call.in_progress"}),
        frame({"type": "response.web_search_call.searching"}),
        completed(FINISHED_RESPONSE),
    ]

    read_stream(lines, on_search=announced.append)

    assert announced == []


def test_reasoning_deltas_are_not_mistaken_for_anything() -> None:
    """The bulk of a stream is reasoning text, and none of it is progress."""
    announced: list[SearchAction] = []
    lines = [frame({"type": "response.reasoning_text.delta", "delta": "想"}) for _ in range(50)]
    lines.append(completed(FINISHED_RESPONSE))

    response = read_stream(lines, on_search=announced.append)

    assert announced == []
    assert response.payload == FINISHED_RESPONSE


def test_an_incomplete_run_still_ends_with_its_response() -> None:
    """Truncation is a terminal event too, and `read_response` names it."""
    truncated = dict(FINISHED_RESPONSE, status="incomplete")
    truncated["incomplete_details"] = {"reason": "max_output_tokens"}
    lines = [frame({"type": "response.incomplete", "response": truncated})]

    response = read_stream(lines)

    assert response.payload == truncated


def test_a_stream_that_stops_before_the_end_carries_no_half_report() -> None:
    """A dropped connection must not look like a response that said nothing useful."""
    lines = [
        search_done("search", queries=["四天工作制"]),
        frame({"type": "response.output_text.delta", "delta": '{"over'}),
    ]

    response = read_stream(lines)

    assert response.payload is None


def test_one_unreadable_frame_does_not_lose_the_run() -> None:
    lines = [
        "data: {not json at all",
        "",
        ": a comment line",
        "data: [DONE]",
        completed(FINISHED_RESPONSE),
    ]

    assert read_stream(lines).payload == FINISHED_RESPONSE


def test_one_page_read_twice_is_one_page() -> None:
    """`find_in_page` is more of a page already open, and the fragment renames it.

    A live run on 2026-09-12 announced 77 search actions against 20-odd distinct
    pages, because every `find_in_page` counted again and every `open_page`
    carried a different `#ws_call_id=`. Told that way, the workbench would
    report a run opening seventy pages, which is not what it did.
    """
    announced: list[SearchAction] = []
    lines = [
        search_done("open_page", url="https://a.example/report#ws_call_id=call_01"),
        search_done("find_in_page", url="https://a.example/report#ws_call_id=call_02"),
        search_done("open_page", url="https://a.example/report"),
        search_done("open_page", url="https://b.example/other"),
        completed(FINISHED_RESPONSE),
    ]

    read_stream(lines, on_search=announced.append)

    pages = {_page_key(action.url or "") for action in announced if action.kind != "search"}
    assert pages == {"https://a.example/report", "https://b.example/other"}


def test_a_query_string_still_names_a_different_page() -> None:
    """Only the fragment is provider bookkeeping; a query is part of the address."""
    assert _page_key("https://a.example/p?id=1") != _page_key("https://a.example/p?id=2")
    assert _page_key("HTTPS://A.example/p#ws_call_id=x") == _page_key("https://a.example/p")
