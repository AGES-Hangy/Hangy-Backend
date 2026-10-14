from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.domain.entities import NearbyEvent, NearbyEvents

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
        limit: int,
    ) -> Sequence[NearbyEvent]: ...


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
        return NearbyEvents(
            items=tuple(
                self.repository.list_nearby(
                    viewer_id=viewer_id,
                    latitude=latitude,
                    longitude=longitude,
                    radius_m=radius_m,
                    limit=limit,
                )
            )
        )
