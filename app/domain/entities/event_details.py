from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.entities.event import Event
from app.domain.entities.tag import Tag
from app.domain.enums import (
    EventAvailableActionEnum,
    EventParticipantStatusEnum,
    UserTypeEnum,
)


@dataclass(frozen=True, slots=True)
class EventDetailsOrganizer:
    user_id: UUID
    name: str | None
    user_type: UserTypeEnum


@dataclass(frozen=True, slots=True)
class EventDetailsParticipant:
    participant_id: UUID
    user_id: UUID
    name: str | None
    user_type: UserTypeEnum
    avatar_url: str | None
    status: EventParticipantStatusEnum
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class EventDetailsData:
    """Persistence facts used by the service to resolve viewer-specific rules."""

    event: Event
    tags: tuple[Tag, ...]
    organizer: EventDetailsOrganizer
    viewer_participation_status: EventParticipantStatusEnum | None
    confirmed_participants_count: int
    confirmed_participants: tuple[EventDetailsParticipant, ...]
    organizer_blocked_viewer: bool


@dataclass(frozen=True, slots=True)
class EventDetailsViewer:
    is_organizer: bool
    participation_status: EventParticipantStatusEnum | None
    can_see_participants: bool
    available_action: EventAvailableActionEnum


@dataclass(frozen=True, slots=True)
class EventParticipantsPreview:
    count: int
    items: tuple[EventDetailsParticipant, ...]


@dataclass(frozen=True, slots=True)
class EventDetails:
    event: Event
    tags: tuple[Tag, ...]
    organizer: EventDetailsOrganizer
    viewer: EventDetailsViewer
    participants_preview: EventParticipantsPreview | None
