__all__ = [
    "AdminTagNotFoundError",
    "AdminTagRepository",
    "AdminTagsService",
    "AuditRepository",
    "CategoryHasTagsError",
    "ParentTagNotCategoryError",
    "ParentTagNotFoundError",
    "TagInUseError",
    "TagNameAlreadyExistsError",
]

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import AuditEvent, Tag
from app.domain.enums import AuditActionEnum, TagTypeEnum


class AdminTagRepository(Protocol):
    def get_by_id(self, tag_id: UUID) -> Tag | None: ...

    def name_exists(self, name: str, parent_id: UUID | None) -> bool: ...

    def create(self, tag: Tag) -> Tag: ...

    def count_children(self, tag_id: UUID) -> int: ...

    def count_usage(self, tag_id: UUID) -> int: ...

    def delete(self, tag_id: UUID) -> None: ...


class AuditRepository(Protocol):
    def add(self, event: AuditEvent) -> None: ...


class ParentTagNotFoundError(Exception):
    """Raised when the informed parent_id does not match any tag."""


class ParentTagNotCategoryError(Exception):
    """Raised when the informed parent is a micro tag; the tree has two levels."""


class TagNameAlreadyExistsError(Exception):
    """Raised when a sibling at the same level already uses the tag name."""


class AdminTagNotFoundError(Exception):
    """Raised when the tag selected for deletion does not exist."""


class CategoryHasTagsError(Exception):
    """Raised when an admin tries to delete a non-empty category."""


class TagInUseError(Exception):
    """Raised when a tag is still associated with users or events."""

    def __init__(self, usage_count: int) -> None:
        self.usage_count = usage_count
        super().__init__("Tag is in use")


class AdminTagsService:
    """Business rules for the admin tag management endpoints."""

    def __init__(
        self, repository: AdminTagRepository, audit_repository: AuditRepository
    ) -> None:
        self.repository = repository
        self.audit_repository = audit_repository

    def create_tag(self, tag: Tag, actor_id: UUID, now: datetime | None = None) -> Tag:
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
        self.audit_repository.add(
            AuditEvent(
                action=AuditActionEnum.TAG_CREATED,
                actor_id=actor_id,
                target_id=created.tag_id,
                created_at=now or datetime.now(UTC),
            )
        )
        return created

    def delete_tag(
        self,
        tag_id: UUID,
        actor_id: UUID,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> None:
        """Delete a tag while protecting non-empty categories and active links."""
        tag = self.repository.get_by_id(tag_id)
        if tag is None:
            raise AdminTagNotFoundError

        if (
            tag.tag_type is TagTypeEnum.MACRO
            and self.repository.count_children(tag_id) > 0
        ):
            raise CategoryHasTagsError

        usage_count = self.repository.count_usage(tag_id)
        if usage_count > 0 and not force:
            raise TagInUseError(usage_count)

        self.repository.delete(tag_id)
        self.audit_repository.add(
            AuditEvent(
                action=AuditActionEnum.TAG_DELETED,
                actor_id=actor_id,
                target_id=tag_id,
                created_at=now or datetime.now(UTC),
                metadata={"name": tag.tag_name, "usage_count": usage_count},
            )
        )
