from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.entities.event import Event, EventLocationView
from app.domain.enums import EventParticipantStatusEnum, EventPrivacyEnum


@dataclass(frozen=True, slots=True)
class UserEventParticipation:
    """An event of a user as persisted, before the viewer's rules apply."""

    event: Event
    participation_status: EventParticipantStatusEnum | None


@dataclass(frozen=True, slots=True)
class UserEvent:
    """An event as listed by a profile tab."""

    event_id: UUID
    title: str
    starts_at: datetime
    privacy: EventPrivacyEnum
    # The location the viewer may see of the event; see `resolve_location`.
    location: EventLocationView
    # The profile owner's own participation; unset when they only created or
    # favorited the event, and always hidden from other viewers.
    participation_status: EventParticipantStatusEnum | None = None
    cover_photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class UserEventsPage:
    items: tuple[UserEvent, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class UserEventsTabs:
    """Every tab of a profile; None marks a tab the viewer is not shown."""

    history: UserEventsPage | None = None
    created: UserEventsPage | None = None
    interests: UserEventsPage | None = None
    confirmed: UserEventsPage | None = None
