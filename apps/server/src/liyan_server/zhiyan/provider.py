"""The replaceable provider seam for one 知言 run.

The domain depends on this contract, not on DeepSeek. A provider receives a
fully-approved request and returns raw text plus the search actions it performed;
deciding whether that text is a 知言报告 belongs to `acceptance`.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from liyan_server.zhiyan.failures import ZhiyanRunFailure

type SearchActionKind = Literal["search", "open_page", "find_in_page"]


@dataclass(frozen=True)
class SearchAction:
    """One action the provider's server-side web search actually performed."""

    kind: SearchActionKind
    query: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class ToolPolicy:
    """What external tooling a run may use. The provider owns its own search caps."""

    web_search_enabled: bool = True


@dataclass(frozen=True)
class ZhiyanRequest:
    """Everything a 知言 run is allowed to send to a provider."""

    model: str
    prompt_version: str
    instructions: str
    input_text: str
    report_schema: dict[str, object]
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy)


@dataclass(frozen=True)
class ZhiyanProviderResult:
    report_text: str
    search_actions: tuple[SearchAction, ...]
    model: str
    response_id: str | None = None

    @property
    def opened_urls(self) -> tuple[str, ...]:
        """The pages the provider actually opened, in the order it opened them."""
        return tuple(
            action.url
            for action in self.search_actions
            if action.kind in {"open_page", "find_in_page"} and action.url
        )


class ZhiyanProviderFailure(ZhiyanRunFailure):
    """The provider could not be reached, or answered with something unusable."""


class ZhiyanProvider(Protocol):
    def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult: ...
