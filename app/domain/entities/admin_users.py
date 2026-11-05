from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import ModerationStatusEnum


@dataclass(frozen=True, slots=True)
class AdminUserRecord:
    """A user as stored, before the moderation status is derived."""

    user_id: UUID
    name: str | None
    created_at: datetime
    banned_at: datetime | None
    suspended_until: datetime | None
    event_count: int
    report_count: int


@dataclass(frozen=True, slots=True)
class AdminUserItem:
    user_id: UUID
    name: str | None
    moderation_status: ModerationStatusEnum
    suspended_until: datetime | None
    event_count: int
    report_count: int


@dataclass(frozen=True, slots=True)
class AdminUsersPage:
    items: tuple[AdminUserItem, ...]
    next_cursor: str | None
