from dataclasses import dataclass
from typing import Protocol

from liyan_server.liyan.failures import LiyanRunFailure


@dataclass(frozen=True)
class LiyanRequest:
    model: str
    prompt_version: str
    instructions: str
    input_text: str
    article_schema: dict[str, object]


@dataclass(frozen=True)
class LiyanProviderResult:
    article_text: str
    model: str
    response_id: str | None = None


class LiyanProviderFailure(LiyanRunFailure):
    pass


class LiyanProvider(Protocol):
    def generate(self, request: LiyanRequest) -> LiyanProviderResult: ...
