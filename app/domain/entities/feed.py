from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.entities.tag import Tag
from app.domain.enums import EventPrivacyEnum


@dataclass(frozen=True, slots=True)
class FeedItem:
    """An event as it is rendered by a Home feed card."""

    event_id: UUID
    title: str
    # PRIVATE events reach the feed without their schedule and venue.
    event_date: datetime | None
    privacy: EventPrivacyEnum
    participants_count: int
    location_name: str | None = None
    cover_photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class FeedSection:
    """Events of a macro tag, paginated on its own."""

    tag: Tag
    items: tuple[FeedItem, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class Feed:
    sections: tuple[FeedSection, ...]
