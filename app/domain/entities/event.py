from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import EventPrivacyEnum, EventStatusEnum


@dataclass(frozen=True, slots=True)
class NewEvent:
    """An event as requested by its organizer, before it is persisted."""

    event_creator_id: UUID
    event_title: str
    event_latitude: float
    event_longitude: float
    starts_at: datetime
    ends_at: datetime
    event_privacy: EventPrivacyEnum
    event_description: str | None = None
    location_name: str | None = None
    max_participants: int | None = None
    cover_photo_url: str | None = None
    tag_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class Event:
    event_id: UUID | None
    event_creator_id: UUID
    event_title: str
    event_latitude: float
    event_longitude: float
    starts_at: datetime
    ends_at: datetime
    event_status: EventStatusEnum
    event_privacy: EventPrivacyEnum
    created_at: datetime
    updated_at: datetime
    event_description: str | None = None
    location_name: str | None = None
    max_participants: int | None = None
    cover_photo_url: str | None = None
    deleted_at: datetime | None = None
