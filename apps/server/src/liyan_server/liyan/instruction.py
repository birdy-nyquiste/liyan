from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class InstructionText(BaseModel):
    type: Literal["text"] = "text"
    text: str


class InstructionCapsule(BaseModel):
    type: Literal["capsule"] = "capsule"
    task_version_id: UUID
    report_id: UUID
    item_id: str
    #: Which kind of 知言报告 the cited item belongs to. Defaults to 来源 so an
    #: instruction recorded before 主题 existed keeps resolving unchanged.
    report_kind: Literal["source", "theme"] = "source"

    @property
    def identity(self) -> tuple[UUID, str]:
        return self.report_id, self.item_id


type InstructionPart = Annotated[
    InstructionText | InstructionCapsule,
    Field(discriminator="type"),
]


class InstructionDocument(BaseModel):
    content: list[InstructionPart] = Field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> "InstructionDocument":
        return cls(content=[InstructionText(text=text)] if text else [])

    def plain_text(self) -> str:
        return "".join(
            part.text if isinstance(part, InstructionText) else "[知言引用]"
            for part in self.content
        )
