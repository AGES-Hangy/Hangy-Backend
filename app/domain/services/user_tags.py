from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from app.domain.entities import Tag
from app.domain.enums import TagTypeEnum


class UserTagsRepository(Protocol):
    def find_by_ids(self, tag_ids: Collection[UUID]) -> list[Tag]: ...

    def replace_user_tags(
        self, user_id: UUID, tag_ids: Collection[UUID]
    ) -> list[Tag]: ...


class UserTagNotFoundError(Exception):
    """Raised when a selected tag_id does not exist."""


class OnlyMicroTagsSelectableError(Exception):
    """Raised when a selected tag is a macro tag."""


class UserTagsService:
    """Replace the authenticated user's interest tags as a single set."""

    def __init__(self, repository: UserTagsRepository) -> None:
        self.repository = repository

    def replace_tags(self, user_id: UUID, tag_ids: Collection[UUID]) -> list[Tag]:
        if tag_ids:
            tags = self.repository.find_by_ids(tag_ids)
            if len(tags) != len(tag_ids):
                raise UserTagNotFoundError
            if any(tag.tag_type is TagTypeEnum.MACRO for tag in tags):
                raise OnlyMicroTagsSelectableError

        return self.repository.replace_user_tags(user_id, tag_ids)
