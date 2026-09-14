from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import TagTypeEnum


class TagOutput(BaseModel):
    """A tag as returned to API clients."""

    id: UUID
    name: str
    type: TagTypeEnum
    parent_id: UUID | None


class TagLeafOutput(BaseModel):
    id: UUID
    name: str
    type: Literal["MICRO"]


class TagNodeOutput(BaseModel):
    id: UUID
    name: str
    type: Literal["MACRO"]
    children: list[TagLeafOutput]
