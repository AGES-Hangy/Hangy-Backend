from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.entities.event import Event, EventLocationView
from app.domain.entities.tag import Tag
from app.domain.enums import EventParticipantStatusEnum, EventPrivacyEnum


@dataclass(frozen=True, slots=True)
class FeedEvent:
    """Persistence facts of a feed card, before the viewer's rules apply."""

    event: Event
    participants_count: int
    viewer_participation_status: EventParticipantStatusEnum | None
    viewer_favorited: bool = False
    # The event's own micro tags under the section's macro tag.
    tags: tuple[Tag, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedItem:
    """An event as it is rendered by a Home feed card."""

    event_id: UUID
    title: str
    # PRIVATE events reach the feed without their schedule.
    event_date: datetime | None
    privacy: EventPrivacyEnum
    participants_count: int
    # The location this viewer may see: only the neighborhood of a PRIVATE
    # event they were not approved for.
    location: EventLocationView
    cover_photo_url: str | None = None
    # Lets the card's favorite toggle start in the right state without
    # fetching each event's details.
    is_favorited: bool = False
    # The event's own micro tags under this section's macro tag — the reason
    # it matched here, and what the card should show instead of repeating the
    # section's own macro tag on every item.
    tags: tuple[Tag, ...] = ()


@dataclass(frozen=True, slots=True)
class FeedSection:
    """Events of a macro tag, paginated on its own."""

    tag: Tag
    items: tuple[FeedItem, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class Feed:
    sections: tuple[FeedSection, ...]
