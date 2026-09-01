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
