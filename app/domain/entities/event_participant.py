from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import EventParticipantStatusEnum


@dataclass(frozen=True, slots=True)
class EventParticipant:
    participant_id: UUID | None
    user_id: UUID
    event_id: UUID
    status: EventParticipantStatusEnum
    joined_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EventParticipantListItem:
    participant_id: UUID
    user_id: UUID
    user_name: str | None
    status: EventParticipantStatusEnum
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class EventParticipantCounts:
    confirmed: int
    # None when the viewer is not the organizer: pending requests are not
    # exposed, even as a count, to anyone else.
    pending: int | None


@dataclass(frozen=True, slots=True)
class EventParticipantsPage:
    items: tuple[EventParticipantListItem, ...]
    counts: EventParticipantCounts
    next_cursor: str | None
