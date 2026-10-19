import math
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.domain.entities import NearbyEvent, NearbyEventCandidate, NearbyEvents
from app.domain.enums import EventParticipantStatusEnum, LocationPrecisionEnum
from app.domain.services.event_location import resolve_location

MAX_NEARBY_RADIUS_M = 50_000
MIN_NEARBY_RADIUS_M = 1
DEFAULT_NEARBY_LIMIT = 50
MAX_NEARBY_LIMIT = 100
MIN_LATITUDE, MAX_LATITUDE = -90.0, 90.0
MIN_LONGITUDE, MAX_LONGITUDE = -180.0, 180.0


class NearbyRepository(Protocol):
    def list_nearby(
        self,
        viewer_id: UUID,
        latitude: float,
        longitude: float,
        radius_m: int,
    ) -> Sequence[NearbyEventCandidate]: ...


class InvalidNearbyCoordinatesError(Exception):
    """Raised when the map center is outside valid geographic coordinates."""


class NearbyRadiusExceededError(Exception):
    """Raised when a nearby search exceeds the supported radius."""


class InvalidNearbyLimitError(Exception):
    """Raised when a nearby search page size is outside accepted bounds."""


class NearbyService:
    def __init__(self, repository: NearbyRepository) -> None:
        self.repository = repository

    def get_nearby(
        self,
        viewer_id: UUID,
        latitude: float,
        longitude: float,
        radius_m: int,
        limit: int = DEFAULT_NEARBY_LIMIT,
    ) -> NearbyEvents:
        if not (
            MIN_LATITUDE <= latitude <= MAX_LATITUDE
            and MIN_LONGITUDE <= longitude <= MAX_LONGITUDE
        ):
            raise InvalidNearbyCoordinatesError
        if not MIN_NEARBY_RADIUS_M <= radius_m <= MAX_NEARBY_RADIUS_M:
            raise NearbyRadiusExceededError
        if not 1 <= limit <= MAX_NEARBY_LIMIT:
            raise InvalidNearbyLimitError
        candidates = self.repository.list_nearby(
            viewer_id=viewer_id,
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
        )
        nearby: list[NearbyEvent] = []
        for candidate in candidates:
            event = candidate.event
            location = resolve_location(
                event,
                is_organizer=event.event_creator_id == viewer_id,
                participation_status=candidate.viewer_participation_status,
            )
            distance_m = _distance_m(
                latitude, longitude, location.latitude, location.longitude
            )
            if distance_m > radius_m:
                continue
            if location.precision is LocationPrecisionEnum.APPROXIMATE:
                distance_m = round(distance_m / 100) * 100
            nearby.append(
                NearbyEvent(
                    event_id=event.event_id,
                    title=event.event_title,
                    event_date=event.starts_at,
                    latitude=location.latitude,
                    longitude=location.longitude,
                    location_name=location.label,
                    cover_photo_url=event.cover_photo_url,
                    distance_m=distance_m,
                    participants_count=(
                        candidate.participants_count
                        if location.precision is LocationPrecisionEnum.EXACT
                        else None
                    ),
                    is_confirmed=(
                        candidate.viewer_participation_status
                        is EventParticipantStatusEnum.CONFIRMED
                    ),
                    privacy=event.event_privacy,
                    location_precision=location.precision,
                    location_radius_m=location.radius_m,
                )
            )
        nearby.sort(key=lambda item: (item.distance_m, item.event_id))
        return NearbyEvents(items=tuple(nearby[:limit]))


def _distance_m(
    origin_latitude: float,
    origin_longitude: float,
    event_latitude: float,
    event_longitude: float,
) -> int:
    latitude_delta = math.radians(event_latitude - origin_latitude)
    longitude_delta = math.radians(event_longitude - origin_longitude)
    origin_latitude = math.radians(origin_latitude)
    event_latitude = math.radians(event_latitude)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(origin_latitude)
        * math.cos(event_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    return round(2 * 6_371_000 * math.asin(math.sqrt(haversine)))
