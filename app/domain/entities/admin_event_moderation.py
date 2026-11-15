__all__ = [
    "EventForModeration",
    "EventModerationAction",
    "EventModerationResult",
    "RemoveEventAction",
]

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import EventModerationStatusEnum, ReportStatusEnum


@dataclass(frozen=True, slots=True)
class RemoveEventAction:
    report_id: UUID | None = None


EventModerationAction = RemoveEventAction


@dataclass(frozen=True, slots=True)
class EventForModeration:
    """An event as the moderation flow needs it, including already removed ones."""

    event_id: UUID
    event_creator_id: UUID
    event_title: str
    moderation_status: EventModerationStatusEnum
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventModerationResult:
    event_id: UUID
    moderation_status: EventModerationStatusEnum
    removed_at: datetime
    report_id: UUID | None
    report_status: ReportStatusEnum | None
