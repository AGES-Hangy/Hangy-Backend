from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import EventPrivacyEnum, LocationPrecisionEnum


@dataclass(frozen=True, slots=True)
class NearbyEvent:
    event_id: UUID
    title: str
    event_date: datetime
    latitude: float
    longitude: float
    location_name: str | None
    cover_photo_url: str | None
    distance_m: int
    participants_count: int
    is_confirmed: bool
    privacy: EventPrivacyEnum
    location_precision: LocationPrecisionEnum = LocationPrecisionEnum.EXACT
    location_radius_m: int | None = None


@dataclass(frozen=True, slots=True)
class NearbyEvents:
    items: tuple[NearbyEvent, ...]
