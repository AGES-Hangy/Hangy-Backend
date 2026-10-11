from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import (
    EventPrivacyEnum,
    EventStatusEnum,
    LocationPrecisionEnum,
)


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
    location_neighborhood: str | None = None
    location_city: str | None = None
    max_participants: int | None = None
    cover_photo_url: str | None = None
    tag_ids: tuple[UUID, ...] = ()
    # Filled in by the service: the approximate point is derived from the id,
    # so the id cannot be left to the database default.
    event_id: UUID | None = None
    approx_latitude: float | None = None
    approx_longitude: float | None = None


@dataclass(frozen=True, slots=True)
class Event:
    event_id: UUID | None
    event_creator_id: UUID
    event_title: str
    event_latitude: float
    event_longitude: float
    # Stable offset of the real coordinates, shown to whoever may not see them.
    approx_latitude: float
    approx_longitude: float
    starts_at: datetime
    ends_at: datetime
    event_status: EventStatusEnum
    event_privacy: EventPrivacyEnum
    created_at: datetime
    updated_at: datetime
    event_description: str | None = None
    location_name: str | None = None
    location_neighborhood: str | None = None
    location_city: str | None = None
    max_participants: int | None = None
    cover_photo_url: str | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventUpdate:
    """A partial change requested by an event organizer."""

    event_title: str | None = None
    event_description: str | None = None
    event_latitude: float | None = None
    event_longitude: float | None = None
    location_name: str | None = None
    location_neighborhood: str | None = None
    location_city: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    cover_photo_url: str | None = None
    tag_ids: tuple[UUID, ...] = ()
    fields_to_update: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class EventLocationView:
    """Where an event happens, as one specific viewer is allowed to see it."""

    precision: LocationPrecisionEnum
    latitude: float
    longitude: float
    # Only set for an approximate location: the area drawn instead of a pin.
    radius_m: int | None
    label: str | None
