__all__ = ["AdminTagOutput", "CreateAdminTagInput"]

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import TagTypeEnum

# Matches the length of the `tag.tag_name` column.
MAX_TAG_NAME_LENGTH = 50


class CreateAdminTagInput(BaseModel):
    """Body of POST /admin/tags: a category (no parent) or a tag inside one."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=MAX_TAG_NAME_LENGTH)
    parent_id: UUID | None = None


class AdminTagOutput(BaseModel):
    """A tag as returned by the admin tag endpoints."""

    tag_id: UUID
    name: str
    parent_id: UUID | None
    type: TagTypeEnum
