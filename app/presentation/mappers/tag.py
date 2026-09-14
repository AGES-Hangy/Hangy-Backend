from uuid import UUID

from app.domain.enums import TagTypeEnum
from app.domain.services import InvalidTagFilterError


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
