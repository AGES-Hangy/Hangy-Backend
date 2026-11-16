from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import (
    EventModerationStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    ModerationStatusEnum,
)

__all__ = [
    "AdminEventDetail",
    "AdminEventDetailRecord",
    "AdminEventMetrics",
    "AdminEventOrganizer",
    "AdminEventOrganizerRecord",
]


@dataclass(frozen=True, slots=True)
class AdminEventMetrics:
    participant_count: int
    pending_count: int
    report_count: int
    report_upheld_count: int


@dataclass(frozen=True, slots=True)
class AdminEventOrganizerRecord:
    """The organizer as stored, before the moderation status is derived."""

    user_id: UUID
    name: str | None
    photo_url: str | None
    banned_at: datetime | None
    suspended_until: datetime | None
    event_count: int
    report_count: int


@dataclass(frozen=True, slots=True)
class AdminEventOrganizer:
    user_id: UUID
    name: str | None
    photo_url: str | None
    moderation_status: ModerationStatusEnum
    event_count: int
    report_count: int


@dataclass(frozen=True, slots=True)
class AdminEventDetailRecord:
    event_id: UUID
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    location_name: str | None
    location_neighborhood: str | None
    location_city: str | None
    latitude: float
    longitude: float
    privacy: EventPrivacyEnum
    status: EventStatusEnum
    moderation_status: EventModerationStatusEnum
    removed_at: datetime | None
    cover_photo_url: str | None
    max_participants: int | None
    created_at: datetime
    tags: tuple[str, ...]
    organizer: AdminEventOrganizerRecord
    metrics: AdminEventMetrics


@dataclass(frozen=True, slots=True)
class AdminEventDetail:
    event_id: UUID
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    location_name: str | None
    location_neighborhood: str | None
    location_city: str | None
    latitude: float
    longitude: float
    privacy: EventPrivacyEnum
    status: EventStatusEnum
    moderation_status: EventModerationStatusEnum
    removed_at: datetime | None
    cover_photo_url: str | None
    max_participants: int | None
    created_at: datetime
    tags: tuple[str, ...]
    organizer: AdminEventOrganizer
    metrics: AdminEventMetrics
