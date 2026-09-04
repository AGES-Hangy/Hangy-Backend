from typing import Protocol
from uuid import UUID

from app.domain.entities import Tag
from app.domain.enums import TagTypeEnum


class TagRepository(Protocol):
    def get_by_id(self, tag_id: UUID) -> Tag | None: ...

    def list_all(self) -> list[Tag]: ...

    def list_by_type(self, tag_type: TagTypeEnum) -> list[Tag]: ...

    def list_children(self, parent_id: UUID) -> list[Tag]: ...

    def get_tree(self) -> list[Tag]: ...


class InvalidTagFilterError(Exception):
    """Raised when the requested tag filters cannot be parsed or combined."""


class TagNotFoundError(Exception):
    """Raised when the requested parent is not an existing macro tag."""


class TagsService:
    """List the system tags, optionally narrowed to a single level of the tree."""

    def __init__(self, repository: TagRepository) -> None:
        self.repository = repository

    def get_tag_tree(self) -> list[Tag]:
        return self.repository.get_tree()

    def get_tags(
        self,
        tag_type: TagTypeEnum | None = None,
        parent_id: UUID | None = None,
    ) -> list[Tag]:
        # Each filter selects a different level, so combining them is ambiguous.
        if tag_type is not None and parent_id is not None:
            raise InvalidTagFilterError

        if parent_id is not None:
            parent = self.repository.get_by_id(parent_id)
            # The tree has exactly two levels, so only a macro tag has children.
            if parent is None or parent.tag_type is not TagTypeEnum.MACRO:
                raise TagNotFoundError
            return self.repository.list_children(parent_id)

        if tag_type is not None:
            return self.repository.list_by_type(tag_type)

        return self.repository.list_all()
