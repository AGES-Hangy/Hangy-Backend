from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import EventPrivacyEnum


@dataclass(frozen=True, slots=True)
class UserEvent:
    """An event as it is listed on someone's profile."""

    event_id: UUID
    title: str
    event_date: datetime
    privacy: EventPrivacyEnum
    location_name: str | None = None
    cover_photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class UserEventsPage:
    items: tuple[UserEvent, ...]
    next_cursor: str | None
