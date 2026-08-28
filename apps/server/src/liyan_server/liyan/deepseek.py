from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from liyan_server.liyan.provider import (
    LiyanProviderFailure,
    LiyanProviderResult,
    LiyanRequest,
)
from liyan_server.provider_usage import provider_usage

ARTICLE_FORMAT_NAME = "liyan_article"
UNAVAILABLE_MESSAGE = "立言服务暂时不可用，请稍后重试。"
UNUSABLE_MESSAGE = "立言服务返回了无法使用的文章，请重试。"


@dataclass(frozen=True)
class ProviderHttpResponse:
    status_code: int
    payload: object
    body_text: str = ""


type PostResponses = Callable[[str, dict[str, str], dict[str, object]], ProviderHttpResponse]


class DeepSeekLiyanProvider:
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

    def generate(self, request: LiyanRequest) -> LiyanProviderResult:
        if not self._api_key:
            raise LiyanProviderFailure(
                "provider_unconfigured",
                UNAVAILABLE_MESSAGE,
                "No DeepSeek API key is configured.",
            )
        response = self._post(
            f"{self._base_url}/responses",
            {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            request_body(request),
        )
        if response.status_code != 200:
            code = (
                "provider_rate_limited"
                if response.status_code == 429
                else "provider_unavailable"
            )
            raise LiyanProviderFailure(
                code,
                UNAVAILABLE_MESSAGE,
                f"DeepSeek responded {response.status_code}: {response.body_text}",
            )
        return provider_result(response.payload, fallback_model=request.model)

    def _post_with_httpx(
        self, url: str, headers: dict[str, str], body: dict[str, object]
    ) -> ProviderHttpResponse:
        import httpx

        try:
            response = httpx.post(
                url, headers=headers, json=body, timeout=self._timeout_seconds
            )
        except httpx.HTTPError as error:
            raise LiyanProviderFailure(
                "provider_unavailable", UNAVAILABLE_MESSAGE, repr(error)
            ) from error
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        return ProviderHttpResponse(response.status_code, payload, response.text[:2_000])


def request_body(request: LiyanRequest) -> dict[str, object]:
    """A stateless structured-output request with no tool access."""
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
        "tools": [],
        "tool_choice": "none",
        "text": {
            "format": {
                "type": "json_schema",
                "name": ARTICLE_FORMAT_NAME,
                "strict": True,
                "schema": request.article_schema,
            }
        },
    }


def provider_result(payload: object, *, fallback_model: str) -> LiyanProviderResult:
    if not isinstance(payload, dict):
        raise LiyanProviderFailure(
            "invalid_provider_response", UNUSABLE_MESSAGE, "Provider returned a non-object."
        )
    # Read before anything can refuse the payload. Every failure below happens
    # after the call returned and was invoiced, so each one owes this: a run
    # that came back unusable cost exactly what a run that came back usable did.
    usage = provider_usage(payload)
    model = payload.get("model")
    resolved_model = model if isinstance(model, str) else fallback_model
    if payload.get("status") not in {None, "completed"}:
        raise LiyanProviderFailure(
            "incomplete_provider_response",
            UNUSABLE_MESSAGE,
            f"Provider status was {payload.get('status')!r}; "
            f"details {payload.get('incomplete_details')!r}.",
            usage=usage,
            model=resolved_model,
        )
    output = payload.get("output")
    if not isinstance(output, list):
        raise LiyanProviderFailure(
            "invalid_provider_response",
            UNUSABLE_MESSAGE,
            "Provider returned no output.",
            usage=usage,
            model=resolved_model,
        )
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "refusal":
                raise LiyanProviderFailure(
                    "provider_refused",
                    UNUSABLE_MESSAGE,
                    "Provider refused the article.",
                    usage=usage,
                    model=resolved_model,
                )
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                texts.append(cast(str, part["text"]))
    article_text = _unfenced("".join(texts).strip())
    if not article_text:
        present = sorted({str(item.get("type")) for item in output if isinstance(item, dict)})
        raise LiyanProviderFailure(
            "invalid_provider_response",
            UNUSABLE_MESSAGE,
            f"Provider returned no output text; output items were {present or ['none']}.",
            usage=usage,
            model=resolved_model,
        )
    response_id = payload.get("id")
    return LiyanProviderResult(
        article_text=article_text,
        model=resolved_model,
        response_id=response_id if isinstance(response_id, str) else None,
        usage=usage,
    )


def _unfenced(text: str) -> str:
    if not text.startswith("```"):
        return text
    body = text[3:]
    newline = body.find("\n")
    if newline == -1 or (body[:newline].strip() and not body[:newline].strip().isalpha()):
        return text
    closing = body[newline + 1 :].rstrip()
    return closing[:-3].strip() if closing.endswith("```") else text
