from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.domain.enums import AuditActionEnum, ModerationStatusEnum

__all__ = [
    "AdminModerationActor",
    "AdminModerationEntry",
    "AdminUserDetail",
    "AdminUserDetailRecord",
    "AdminUserItem",
    "AdminUserMetrics",
    "AdminUserRecord",
    "AdminUsersPage",
]


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


@dataclass(frozen=True, slots=True)
class AdminUserMetrics:
    event_count: int
    event_cancelled_count: int
    report_count: int
    report_upheld_count: int


@dataclass(frozen=True, slots=True)
class AdminModerationActor:
    user_id: UUID
    name: str | None


@dataclass(frozen=True, slots=True)
class AdminModerationEntry:
    action: AuditActionEnum
    actor: AdminModerationActor | None
    occurred_at: datetime
    report_id: UUID | None


@dataclass(frozen=True, slots=True)
class AdminUserDetailRecord:
    """A user's moderation file as stored, before the status is derived."""

    user_id: UUID
    name: str | None
    email: str
    created_at: datetime
    banned_at: datetime | None
    suspended_until: datetime | None
    metrics: AdminUserMetrics
    history: tuple[AdminModerationEntry, ...]


@dataclass(frozen=True, slots=True)
class AdminUserDetail:
    user_id: UUID
    name: str | None
    email: str
    member_since: date
    moderation_status: ModerationStatusEnum
    banned_at: datetime | None
    suspended_until: datetime | None
    metrics: AdminUserMetrics
    moderation_history: tuple[AdminModerationEntry, ...]
