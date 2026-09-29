from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import TagTypeEnum

MAX_USER_TAGS = 20


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


class TagParentOutput(BaseModel):
    id: UUID
    name: str


class UserTagOutput(BaseModel):
    """A user interest tag, with its macro tag nested for display."""

    id: UUID
    name: str
    parent: TagParentOutput | None


class UserTagsOutput(BaseModel):
    tags: list[UserTagOutput]


class ReplaceUserTagsInput(BaseModel):
    """The final set of tag ids the user is interested in."""

    tag_ids: list[UUID] = Field(default_factory=list, max_length=MAX_USER_TAGS)
