from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from app.domain.entities.event import Event, EventLocationView
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    SearchResultType,
)


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Filters applied to the event block of a search."""

    tag_ids: tuple[UUID, ...] = ()
    date_from: date | None = None
    date_to: date | None = None


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Parameters of a search request, reusable for preview and per-type pagination."""

    viewer_id: UUID
    query: str | None = None
    preview_limit: int = 5
    filters: SearchFilters = field(default_factory=SearchFilters)
    result_type: SearchResultType | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SearchEventCandidate:
    """Persistence facts of an event matched by search before visibility rules."""

    event: Event
    participants_count: int
    viewer_participation_status: EventParticipantStatusEnum | None


@dataclass(frozen=True, slots=True)
class SearchEventItem:
    """An event item in the search results after visibility and location resolution."""

    event_id: UUID
    title: str
    event_date: datetime
    location: EventLocationView
    privacy: EventPrivacyEnum
    is_preview: bool
    description: str | None
    participants_count: int | None
    cover_photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class SearchBusinessItem:
    """A business profile item in the search results."""

    user_id: UUID
    business_name: str | None
    name: str | None
    description: str | None = None
    address: str | None = None
    photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class SearchUserItem:
    """A personal profile item in the search results."""

    user_id: UUID
    name: str | None
    description: str | None = None
    city: str | None = None
    state: str | None = None
    photo_url: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResultBlock[T]:
    """A categorized block of search results with its own total and pagination flag."""

    items: tuple[T, ...]
    total: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Categorized search results across events, businesses, and users."""

    query: str | None
    applied_filters: SearchFilters
    events: SearchResultBlock[SearchEventItem]
    businesses: SearchResultBlock[SearchBusinessItem]
    users: SearchResultBlock[SearchUserItem]


__all__ = [
    "SearchBusinessItem",
    "SearchEventCandidate",
    "SearchEventItem",
    "SearchFilters",
    "SearchQuery",
    "SearchResult",
    "SearchResultBlock",
    "SearchUserItem",
]
