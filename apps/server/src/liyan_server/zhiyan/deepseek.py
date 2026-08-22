"""The DeepSeek Responses API adapter behind the 知言 provider seam.

See ADR-0004. The endpoint is OpenAI-compatible `POST /responses`, native
`web_search` executes on DeepSeek's server, `text.format` carries the JSON Schema,
and the contract is stateless: `store` is always false and no request may rely on
`previous_response_id` or a server-side conversation.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

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


@dataclass(frozen=True)
class ProviderHttpResponse:
    status_code: int
    payload: object
    body_text: str = ""


type PostResponses = Callable[[str, dict[str, str], dict[str, object]], ProviderHttpResponse]


class DeepSeekZhiyanProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: int = 300,
        post: PostResponses | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._post = post or self._post_with_httpx

    def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
        if not self._api_key:
            raise ZhiyanProviderFailure(
                "provider_unconfigured",
                UNAVAILABLE_MESSAGE,
                internal_error="No DeepSeek API key is configured.",
            )
        response = self._post(
            f"{self._base_url}/responses",
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            request_body(request),
        )
        if response.status_code != 200:
            raise ZhiyanProviderFailure(
                "provider_unavailable",
                UNAVAILABLE_MESSAGE,
                internal_error=f"DeepSeek responded {response.status_code}: {response.body_text}",
            )
        return provider_result(response.payload, fallback_model=request.model)

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


def request_body(request: ZhiyanRequest) -> dict[str, object]:
    """The exact stateless Responses API request one 知言 run may send."""
    tools: list[dict[str, object]] = (
        [{"type": WEB_SEARCH_TOOL_TYPE}] if request.tool_policy.web_search_enabled else []
    )
    return {
        "model": request.model,
        "instructions": request.instructions,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": request.input_text}],
            }
        ],
        "store": False,
        "tools": tools,
        "tool_choice": "auto",
        "text": {
            "format": {
                "type": "json_schema",
                "name": REPORT_FORMAT_NAME,
                "strict": True,
                "schema": request.report_schema,
            }
        },
    }


def provider_result(payload: object, *, fallback_model: str) -> ZhiyanProviderResult:
    if not isinstance(payload, dict):
        raise ZhiyanProviderFailure(
            "invalid_provider_response",
            UNUSABLE_MESSAGE,
            internal_error="DeepSeek returned a non-object response.",
        )
    status = payload.get("status")
    if status not in {None, "completed"}:
        raise ZhiyanProviderFailure(
            "incomplete_provider_response",
            UNUSABLE_MESSAGE,
            internal_error=f"DeepSeek response status was {status!r}.",
        )
    output = payload.get("output")
    if not isinstance(output, list):
        raise ZhiyanProviderFailure(
            "invalid_provider_response",
            UNUSABLE_MESSAGE,
            internal_error="DeepSeek response carried no output items.",
        )
    actions: list[SearchAction] = []
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "web_search_call":
            action = _search_action(item.get("action"))
            if action is not None:
                actions.append(action)
        elif item.get("type") == "message":
            texts.extend(_message_texts(item))
    report_text = "".join(texts).strip()
    if not report_text:
        raise ZhiyanProviderFailure(
            "invalid_provider_response",
            UNUSABLE_MESSAGE,
            internal_error="DeepSeek response carried no output text.",
        )
    model = payload.get("model")
    response_id = payload.get("id")
    return ZhiyanProviderResult(
        report_text=report_text,
        search_actions=tuple(actions),
        model=model if isinstance(model, str) else fallback_model,
        response_id=response_id if isinstance(response_id, str) else None,
    )


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


def _message_texts(item: dict[str, object]) -> list[str]:
    content = item.get("content")
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "refusal":
            raise ZhiyanProviderFailure(
                "provider_refused",
                UNUSABLE_MESSAGE,
                internal_error="DeepSeek refused to produce a report.",
            )
        if part.get("type") == "output_text" and isinstance(part.get("text"), str):
            texts.append(cast(str, part["text"]))
    return texts
