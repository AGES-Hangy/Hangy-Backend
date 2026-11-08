__all__ = [
    "AdminTagNotFoundError",
    "AdminTagRepository",
    "AdminTagsService",
    "CategoryHasTagsError",
    "ParentTagNotCategoryError",
    "ParentTagNotFoundError",
    "TagInUseError",
    "TagNameAlreadyExistsError",
]

from typing import Protocol
from uuid import UUID

from app.domain.entities import Tag
from app.domain.enums import AuditActionEnum, AuditTargetTypeEnum, TagTypeEnum
from app.domain.services.audit_logger import AuditLogger


class AdminTagRepository(Protocol):
    def get_by_id(self, tag_id: UUID) -> Tag | None: ...

    def name_exists(
        self, name: str, parent_id: UUID | None, *, exclude_tag_id: UUID | None = None
    ) -> bool: ...

    def create(self, tag: Tag) -> Tag: ...

    def rename(self, tag_id: UUID, name: str) -> Tag: ...

    def count_children(self, tag_id: UUID) -> int: ...

    def count_usage(self, tag_id: UUID) -> int: ...

    def delete(self, tag_id: UUID) -> None: ...

    def commit(self) -> None: ...


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

    def rename_tag(self, tag_id: UUID, name: str, actor_id: UUID) -> Tag:
        """Rename a category or micro tag; its parent_id never changes.

        Records a TAG_UPDATED audit event with the old and new name, unless
        the name is unchanged.
        """
        tag = self.repository.get_by_id(tag_id)
        if tag is None:
            raise AdminTagNotFoundError

        if name == tag.tag_name:
            return tag

        if self.repository.name_exists(name, tag.tag_parent_id, exclude_tag_id=tag_id):
            raise TagNameAlreadyExistsError

        renamed = self.repository.rename(tag_id, name)
        self.audit_logger.record(
            actor_id=actor_id,
            action=AuditActionEnum.TAG_UPDATED,
            target_type=AuditTargetTypeEnum.TAG,
            target_id=tag_id,
            metadata={"old_name": tag.tag_name, "new_name": name},
        )
        self.repository.commit()
        return renamed

    def delete_tag(
        self,
        tag_id: UUID,
        actor_id: UUID,
        *,
        force: bool = False,
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

        # Recorded before the delete so the snapshot label still finds the tag
        # name. Nothing is committed until the commit below, so a failed delete
        # leaves no audit row behind.
        self.audit_logger.record(
            actor_id=actor_id,
            action=AuditActionEnum.TAG_DELETED,
            target_type=AuditTargetTypeEnum.TAG,
            target_id=tag_id,
            metadata={"name": tag.tag_name, "usage_count": usage_count},
        )
        self.repository.delete(tag_id)
        self.repository.commit()
