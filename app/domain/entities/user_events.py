from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import EventParticipantStatusEnum


@dataclass(frozen=True, slots=True)
class UserEvent:
    """An event of the authenticated user as listed by a profile tab."""

    event_id: UUID
    title: str
    starts_at: datetime
    participation_status: EventParticipantStatusEnum
    location_name: str | None = None
    cover_photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class UserEventsPage:
    items: tuple[UserEvent, ...]
    next_cursor: str | None
