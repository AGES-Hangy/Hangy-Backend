__all__ = [
    "AdminTagRepository",
    "AdminTagsService",
    "ParentTagNotCategoryError",
    "ParentTagNotFoundError",
    "TagNameAlreadyExistsError",
]

from typing import Protocol
from uuid import UUID

from app.domain.entities import Tag
from app.domain.enums import AuditActionEnum, AuditTargetTypeEnum, TagTypeEnum
from app.domain.services.audit_logger import AuditLogger


class AdminTagRepository(Protocol):
    def get_by_id(self, tag_id: UUID) -> Tag | None: ...

    def name_exists(self, name: str, parent_id: UUID | None) -> bool: ...

    def create(self, tag: Tag) -> Tag: ...

    def commit(self) -> None: ...


class ParentTagNotFoundError(Exception):
    """Raised when the informed parent_id does not match any tag."""


class ParentTagNotCategoryError(Exception):
    """Raised when the informed parent is a micro tag; the tree has two levels."""


class TagNameAlreadyExistsError(Exception):
    """Raised when a sibling at the same level already uses the tag name."""


class AdminTagsService:
    """Business rules for the admin tag management endpoints."""

    def __init__(
        self, repository: AdminTagRepository, audit_logger: AuditLogger
    ) -> None:
        self.repository = repository
        self.audit_logger = audit_logger

    def create_tag(self, tag: Tag, actor_id: UUID) -> Tag:
        """Create a category (no parent) or a micro tag inside a category.

        Records a TAG_CREATED audit event with the admin who created it and when.
        """
        if tag.tag_parent_id is not None:
            parent = self.repository.get_by_id(tag.tag_parent_id)
            if parent is None:
                raise ParentTagNotFoundError
            # Only 2 levels: a micro tag cannot have children.
            if parent.tag_type is not TagTypeEnum.MACRO:
                raise ParentTagNotCategoryError

        # Names are unique per level: among all categories, or inside one category.
        if self.repository.name_exists(tag.tag_name, tag.tag_parent_id):
            raise TagNameAlreadyExistsError

        created = self.repository.create(tag)
        self.audit_logger.record(
            actor_id=actor_id,
            action=AuditActionEnum.TAG_CREATED,
            target_type=AuditTargetTypeEnum.TAG,
            target_id=created.tag_id,
        )
        # The audit write is a savepoint (see AuditLogger): it never fails this
        # commit even when it was itself rolled back.
        self.repository.commit()
        return created
