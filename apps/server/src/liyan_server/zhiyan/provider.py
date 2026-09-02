"""The replaceable provider seam for one 知言 run.

The domain depends on this contract, not on DeepSeek. A provider receives a
fully-approved request and returns raw text plus the search actions it performed;
deciding whether that text is a 知言报告 belongs to `acceptance`.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from liyan_server.provider_usage import ProviderUsage
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
class WrapUp:
    """What a provider says to a run that has searched until its rounds ran out.

    Wording, not policy: the provider decides *when* to ask a run to conclude
    (see `deepseek.continuation_body`), and the prompt that owns the report
    decides what concluding means for it. 知言 tells the model to fall back to
    「暂无法核实」; a 主题知言 run has no such verdict and must drop the item
    instead, so the two cannot share one sentence.
    """

    #: Sent while the run may still search, so it may finish what it started.
    continue_text: str
    #: Sent with the tools taken away. The last call has to return something.
    final_text: str


@dataclass(frozen=True)
class ZhiyanRequest:
    """Everything a 知言-shaped run is allowed to send to a provider.

    Named for 知言, which was the only such run, and now also carries 主题知言:
    both ask one provider for one structured report, with or without search, and
    differ only in the instructions, the schema, and the two sentences above.
    """

    model: str
    prompt_version: str
    instructions: str
    input_text: str
    report_schema: dict[str, object]
    wrap_up: WrapUp
    #: The `text.format` name the provider labels the schema with.
    format_name: str = "zhiyan_report"
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy)


@dataclass(frozen=True)
class ZhiyanProviderResult:
    report_text: str
    search_actions: tuple[SearchAction, ...]
    model: str
    response_id: str | None = None
    #: What the call consumed, when the provider said. Optional because a report
    #: that arrived without one is still a report — see `provider_usage`.
    usage: ProviderUsage | None = None

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
