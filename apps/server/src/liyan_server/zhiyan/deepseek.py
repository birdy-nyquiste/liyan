"""The DeepSeek Responses API adapter behind the 知言 provider seam.

See ADR-0004. The endpoint is OpenAI-compatible `POST /responses`, native
`web_search` executes on DeepSeek's server, `text.format` carries the JSON Schema,
and the contract is stateless: `store` is always false and no request may rely on
`previous_response_id` or a server-side conversation.

One 知言 run is *usually* one call, and is allowed to be more than one. DeepSeek
caps its own server-side search auto-continuation at ten rounds, and a model that
spends all ten searching returns `status: "completed"` carrying only `reasoning`
and `web_search_call` items — every search billed, and no report. Treating that
as a failed run is what made 知言 unreliable exactly in proportion to how much it
searched: see `continuation_body`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from liyan_server.provider_usage import ProviderUsage, combined_usage, provider_usage
from liyan_server.zhiyan.provider import (
    SearchAction,
    SearchActionKind,
    ZhiyanProviderFailure,
    ZhiyanProviderResult,
    ZhiyanRequest,
)

WEB_SEARCH_TOOL_TYPE = "web_search"
REPORT_FORMAT_NAME = "zhiyan_report"
UNAVAILABLE_MESSAGE = "知言服务暂时不可用，请稍后重试。"
UNUSABLE_MESSAGE = "知言服务返回了无法使用的结果，请重试。"

SEARCH_ACTION_KINDS: frozenset[str] = frozenset({"search", "open_page", "find_in_page"})

#: How many extra calls one run may make to get a report out of a provider that
#: stopped mid-search. Two: the first lets the model finish anything it was
#: genuinely in the middle of, the second takes its tools away and asks for the
#: report from what it has already opened. A third has nothing new to offer —
#: if a model with no tools and an explicit instruction to conclude still writes
#: nothing, the run has failed for some other reason.
MAX_SEARCH_CONTINUATIONS = 2

#: Output item types the Responses API accepts back as `input`. Everything else
#: it ignores, so filtering is not required for correctness — it is here so a
#: continuation carries only what the provider will actually read, and so a new
#: item type shows up as a missing continuation rather than as silent bloat.
RESUMABLE_ITEM_TYPES: frozenset[str] = frozenset(
    {
        "message",
        "reasoning",
        "web_search_call",
        "function_call",
        "function_call_output",
        "custom_tool_call",
        "custom_tool_call_output",
    }
)

CONTINUE_INSTRUCTION = """\
以上是你在本次运行中已经完成的检索与推理。检索轮次即将用尽，现在收尾。

- 不要重复已经做过的检索。
- 直接基于上面已经真实打开过的页面输出完整的知言报告 JSON。
- evidence 只能收录上面真实打开过的页面；没有可靠依据的事实一律写「暂无法核实」，
  并且不要为它列出 evidence_ids。
- 只输出符合 JSON Schema 的 JSON，不要附加任何解释。
"""

FINAL_INSTRUCTION = """\
以上是你在本次运行中已经完成的检索与推理。检索轮次已经用尽，不能再调用任何工具。

现在必须基于上面已经真实打开过的页面输出完整的知言报告 JSON。仍然缺少可靠依据的事实
写「暂无法核实」，并且不要为它列出 evidence_ids。只输出符合 JSON Schema 的 JSON。
"""


@dataclass(frozen=True)
class ProviderHttpResponse:
    status_code: int
    payload: object
    body_text: str = ""


type PostResponses = Callable[[str, dict[str, str], dict[str, object]], ProviderHttpResponse]


@dataclass(frozen=True)
class ProviderCall:
    """One `POST /responses` round, read but not yet judged.

    `report_text` is empty when the call produced no message, which is a normal
    intermediate state rather than an error — the difference between the two is
    whether there is another call left to make, and only `analyze` knows that.
    """

    report_text: str
    search_actions: tuple[SearchAction, ...]
    model: str
    response_id: str | None
    usage: ProviderUsage | None
    #: The raw output items, verbatim, so a continuation can hand them straight
    #: back. Verbatim matters: `web_search_call` items carry provider-owned ids
    #: and fields this adapter does not model, and a reconstructed item is a
    #: different item.
    output_items: tuple[dict[str, object], ...] = ()
    item_types: tuple[str, ...] = ()

    @property
    def searches(self) -> int:
        return sum(1 for action in self.search_actions if action.kind == "search")


@dataclass
class _RunTally:
    """What a run has consumed so far, across however many calls it has made.

    Carried separately from the calls themselves because it must survive them:
    when call three times out, what calls one and two cost is still owed, and
    the failure is the only thing left to carry it.
    """

    usages: list[ProviderUsage | None] = field(default_factory=list)
    actions: list[SearchAction] = field(default_factory=list)
    model: str | None = None

    def add(self, call: ProviderCall) -> None:
        self.usages.append(call.usage)
        self.actions.extend(call.search_actions)
        self.model = call.model

    @property
    def usage(self) -> ProviderUsage | None:
        return combined_usage(self.usages)

    @property
    def search_calls(self) -> int | None:
        return (
            sum(1 for action in self.actions if action.kind == "search")
            if self.usages
            else None
        )

    def failure(
        self,
        code: str,
        message: str,
        internal_error: str | None = None,
    ) -> ZhiyanProviderFailure:
        """The same failure it would have raised, plus the bill it ran up."""
        return ZhiyanProviderFailure(
            code,
            message,
            internal_error=internal_error,
            usage=self.usage,
            model=self.model,
            search_calls=self.search_calls,
        )


class DeepSeekZhiyanProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: int = 300,
        post: PostResponses | None = None,
        max_continuations: int = MAX_SEARCH_CONTINUATIONS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._post = post or self._post_with_httpx
        self._max_continuations = max(0, max_continuations)

    def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
        if not self._api_key:
            raise ZhiyanProviderFailure(
                "provider_unconfigured",
                UNAVAILABLE_MESSAGE,
                internal_error="No DeepSeek API key is configured.",
            )
        tally = _RunTally()
        body = request_body(request)
        for remaining in range(self._max_continuations, -1, -1):
            call = self._call(body, tally, fallback_model=request.model)
            tally.add(call)
            if call.report_text:
                return ZhiyanProviderResult(
                    report_text=call.report_text,
                    search_actions=tuple(tally.actions),
                    model=call.model,
                    response_id=call.response_id,
                    usage=tally.usage,
                )
            if remaining == 0 or not _continuable(call, request):
                raise tally.failure(
                    "invalid_provider_response",
                    UNUSABLE_MESSAGE,
                    internal_error=(
                        "DeepSeek response carried no output text after "
                        f"{len(tally.usages)} call(s) and {tally.search_calls} search(es); "
                        f"output items were {list(call.item_types) or ['none']}."
                    ),
                )
            body = continuation_body(
                request,
                prior_items=call.output_items,
                final=remaining == 1,
            )
        raise AssertionError("The continuation loop always returns or raises.")

    def _call(
        self,
        body: dict[str, object],
        tally: _RunTally,
        *,
        fallback_model: str,
    ) -> ProviderCall:
        try:
            response = self._post(
                f"{self._base_url}/responses",
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                body,
            )
        except ZhiyanProviderFailure as transport:
            # `_post` cannot see the tally, so a socket that died on call three
            # would otherwise report a run that cost nothing — when calls one
            # and two are the whole of what a search-heavy run spends. Whatever
            # it knows, plus whatever the run already owes.
            raise tally.failure(
                transport.code, transport.message, transport.internal_error
            ) from transport
        if response.status_code != 200:
            # 429 earns its own code because `zhiyan/recovery` waits twice as
            # long for it as for a generic provider failure. Being refused for
            # asking too often is the one failure where asking again in thirty
            # seconds is how you earn a second one — and 知言 is the operation
            # that saturates a provider, being the long one that searches.
            code = (
                "provider_rate_limited"
                if response.status_code == 429
                else "provider_unavailable"
            )
            raise tally.failure(
                code,
                UNAVAILABLE_MESSAGE,
                internal_error=f"DeepSeek responded {response.status_code}: {response.body_text}",
            )
        return read_response(response.payload, fallback_model=fallback_model, tally=tally)

    def _post_with_httpx(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> ProviderHttpResponse:
        import httpx

        try:
            response = httpx.post(
                url,
                headers=headers,
                json=body,
                timeout=self._timeout_seconds,
            )
        except httpx.HTTPError as error:
            raise ZhiyanProviderFailure(
                "provider_unavailable",
                UNAVAILABLE_MESSAGE,
                internal_error=repr(error),
            ) from error
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        return ProviderHttpResponse(
            status_code=response.status_code,
            payload=payload,
            body_text=response.text[:2_000],
        )


def _continuable(call: ProviderCall, request: ZhiyanRequest) -> bool:
    """Whether asking again could plausibly produce what this call did not.

    Only a run that was *working* is continued. A call that returned nothing at
    all, or one from a run that was never allowed to search, produced no state
    worth resuming — asking it again is a retry, which is `recovery`'s job and
    subject to `recovery`'s limits, not a free extra call inside this one.
    """
    return bool(call.output_items) and request.tool_policy.web_search_enabled


def request_body(request: ZhiyanRequest) -> dict[str, object]:
    """The exact stateless Responses API request one 知言 run may send."""
    return _body(
        request,
        input_items=[_user_message(request.input_text)],
        tools_enabled=request.tool_policy.web_search_enabled,
    )


def continuation_body(
    request: ZhiyanRequest,
    *,
    prior_items: Sequence[dict[str, object]],
    final: bool,
) -> dict[str, object]:
    """Ask again for the report, carrying everything the run has already done.

    The API is stateless and `previous_response_id` is unsupported (ADR-0004),
    so resuming means re-sending: the original 来源 message, then the output
    items of the call that stopped, then one instruction to conclude. Those
    items are the accepted input types — `message`, `reasoning`,
    `web_search_call` — so the model reads the trail of its own
    searches rather than starting over, and the identical prefix makes almost all of it a cache hit.

    `final` takes the tools away. A model asked to conclude while it can still
    search will sometimes search instead, and the last call of a run has to
    return something.
    """
    return _body(
        request,
        input_items=[
            _user_message(request.input_text),
            *(item for item in prior_items if item.get("type") in RESUMABLE_ITEM_TYPES),
            _user_message(FINAL_INSTRUCTION if final else CONTINUE_INSTRUCTION),
        ],
        tools_enabled=not final and request.tool_policy.web_search_enabled,
    )


def _body(
    request: ZhiyanRequest,
    *,
    input_items: Sequence[object],
    tools_enabled: bool,
) -> dict[str, object]:
    tools: list[dict[str, object]] = [{"type": WEB_SEARCH_TOOL_TYPE}] if tools_enabled else []
    return {
        "model": request.model,
        "instructions": request.instructions,
        "input": list(input_items),
        "store": False,
        "tools": tools,
        # `max_tool_calls` is deliberately absent: DeepSeek accepts it and does
        # not enforce it — a run capped at six made twenty — so sending it would
        # read as a bound that is not one. What actually bounds a run's
        # searching is the provider's ten-round cap, and what survives that cap
        # is `continuation_body` rather than any request parameter.
        "tool_choice": "auto" if tools else "none",
        "text": {
            "format": {
                "type": "json_schema",
                "name": REPORT_FORMAT_NAME,
                "strict": True,
                "schema": request.report_schema,
            }
        },
    }


def _user_message(text: str) -> dict[str, object]:
    return {"role": "user", "content": [{"type": "input_text", "text": text}]}


def read_response(
    payload: object,
    *,
    fallback_model: str,
    tally: _RunTally | None = None,
) -> ProviderCall:
    """Read one call's output, without deciding whether the run has failed.

    An empty `report_text` comes back as a `ProviderCall`, not an exception:
    whether "no message" ends the run depends on how many calls are left, which
    is `analyze`'s business. Everything that is unusable *whatever* comes next —
    a non-object payload, a truncated response, a refusal — still raises here.
    """
    billed = tally or _RunTally()
    if not isinstance(payload, dict):
        raise billed.failure(
            "invalid_provider_response",
            UNUSABLE_MESSAGE,
            internal_error="DeepSeek returned a non-object response.",
        )
    usage = provider_usage(payload)
    model = payload.get("model")
    resolved_model = model if isinstance(model, str) else fallback_model
    status = payload.get("status")
    if status not in {None, "completed"}:
        # The details say which of the two very different incompletes this is —
        # a generation cut off at a length bound, or content filtering — and
        # they read identically without it.
        details = payload.get("incomplete_details")
        raise _with(billed, usage, resolved_model, ()).failure(
            "incomplete_provider_response",
            UNUSABLE_MESSAGE,
            internal_error=f"DeepSeek response status was {status!r}; details {details!r}.",
        )
    output = payload.get("output")
    if not isinstance(output, list):
        raise _with(billed, usage, resolved_model, ()).failure(
            "invalid_provider_response",
            UNUSABLE_MESSAGE,
            internal_error="DeepSeek response carried no output items.",
        )
    items = tuple(item for item in output if isinstance(item, dict))
    actions: list[SearchAction] = []
    texts: list[str] = []
    for item in items:
        if item.get("type") == "web_search_call":
            action = _search_action(item.get("action"))
            if action is not None:
                actions.append(action)
        elif item.get("type") == "message":
            texts.extend(_message_texts(item, billed, usage, resolved_model, tuple(actions)))
    return ProviderCall(
        report_text=_unfenced("".join(texts).strip()),
        search_actions=tuple(actions),
        model=resolved_model,
        response_id=payload.get("id") if isinstance(payload.get("id"), str) else None,
        usage=usage,
        output_items=items,
        # Named even when there is no text, and especially then. "No output
        # text" alone is a dead end: a reply that is only web_search_call, one
        # whose message has empty content, and one shaped differently all read
        # identically and call for different fixes. The types are structural —
        # no part of them is 来源 or report content.
        item_types=tuple(sorted({str(item.get("type")) for item in items})),
    )


def provider_result(payload: object, *, fallback_model: str) -> ZhiyanProviderResult:
    """One call's output as a finished result, for callers with no run around it.

    `analyze` does not use this — it must decide between "no message yet" and
    "no message ever" — but a single payload that carries a report is still a
    complete answer, and the offline replays in `test_zhiyan_live_contract` read
    it that way.
    """
    call = read_response(payload, fallback_model=fallback_model)
    if not call.report_text:
        raise ZhiyanProviderFailure(
            "invalid_provider_response",
            UNUSABLE_MESSAGE,
            internal_error=(
                "DeepSeek response carried no output text; "
                f"output items were {list(call.item_types) or ['none']}."
            ),
            usage=call.usage,
            model=call.model,
            search_calls=call.searches,
        )
    return ZhiyanProviderResult(
        report_text=call.report_text,
        search_actions=call.search_actions,
        model=call.model,
        response_id=call.response_id,
        usage=call.usage,
    )


def _with(
    tally: _RunTally,
    usage: ProviderUsage | None,
    model: str,
    actions: tuple[SearchAction, ...],
) -> _RunTally:
    """The tally including the call that is about to fail, which was still billed."""
    tally.usages.append(usage)
    tally.actions.extend(actions)
    tally.model = model
    return tally


def _unfenced(text: str) -> str:
    """Strip a Markdown code fence DeepSeek sometimes wraps structured output in.

    Observed live: the same request returns raw JSON on one call and a
    ```json-fenced body on the next, even with `text.format` set to a strict
    json_schema. Normalising the provider's quirk here keeps acceptance strict
    about receiving real JSON.
    """
    if not text.startswith("```"):
        return text
    body = text[3:]
    newline = body.find("\n")
    if newline == -1:
        return text
    language = body[:newline].strip()
    if language and not language.isalpha():
        return text
    body = body[newline + 1 :]
    closing = body.rstrip()
    if not closing.endswith("```"):
        return text
    return closing[: -len("```")].strip()


def _search_action(action: object) -> SearchAction | None:
    if not isinstance(action, dict):
        return None
    kind = action.get("type")
    if not isinstance(kind, str) or kind not in SEARCH_ACTION_KINDS:
        return None
    query = action.get("query")
    url = action.get("url")
    return SearchAction(
        kind=cast(SearchActionKind, kind),
        query=query if isinstance(query, str) else None,
        url=url if isinstance(url, str) else None,
    )


def _message_texts(
    item: dict[str, object],
    tally: _RunTally,
    usage: ProviderUsage | None,
    model: str,
    actions: tuple[SearchAction, ...],
) -> list[str]:
    content = item.get("content")
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "refusal":
            raise _with(tally, usage, model, actions).failure(
                "provider_refused",
                UNUSABLE_MESSAGE,
                internal_error="DeepSeek refused to produce a report.",
            )
        if part.get("type") == "output_text" and isinstance(part.get("text"), str):
            texts.append(cast(str, part["text"]))
    return texts
