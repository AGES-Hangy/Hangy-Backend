from uuid import UUID

from app.domain.enums import TagTypeEnum
from app.domain.services import InvalidTagFilterError
from app.presentation.dtos import ReplaceUserTagsInput


class TagMapper:
    """Turn raw tag query parameters into the values the domain expects."""

    @staticmethod
    def to_tag_type(value: str | None) -> TagTypeEnum | None:
        if value is None:
            return None
        try:
            return TagTypeEnum(value)
        except ValueError as error:
            raise InvalidTagFilterError from error

    @staticmethod
    def to_parent_id(value: str | None) -> UUID | None:
        if value is None:
            return None
        try:
            return UUID(value)
        except ValueError as error:
            raise InvalidTagFilterError from error


class UserTagsMapper:
    """Turn the replace-tags request body into the ids the domain expects."""

    @staticmethod
    def to_tag_ids(dto: ReplaceUserTagsInput) -> tuple[UUID, ...]:
        # dict.fromkeys drops duplicates without losing the client's order.
        return tuple(dict.fromkeys(dto.tag_ids))
