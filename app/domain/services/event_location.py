import hashlib
import hmac
import math
from uuid import UUID

from app.config import settings
from app.domain.entities import Event, EventLocationView
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    LocationPrecisionEnum,
)

EARTH_RADIUS_M = 6_371_000.0
# The offset never reaches zero, so the real address is never the center of
# the area shown, and it stays below the area radius, so it is always inside.
MIN_APPROXIMATION_OFFSET_M = 150.0
MAX_APPROXIMATION_OFFSET_M = 350.0


def approximate_point(
    event_id: UUID, latitude: float, longitude: float
) -> tuple[float, float]:
    """Offset a coordinate by a distance and direction fixed for this event.

    The offset is derived from the event id instead of drawn at random: a new
    point per request could be averaged back into the real address. The secret
    keeps anyone from redoing the math from the id, which is public.
    """
    digest = hmac.new(
        settings.location_obfuscation_secret.encode(),
        event_id.bytes,
        hashlib.sha256,
    ).digest()
    bearing = math.radians(int.from_bytes(digest[0:4]) / 2**32 * 360)
    distance = MIN_APPROXIMATION_OFFSET_M + (
        int.from_bytes(digest[4:8])
        / (2**32 - 1)
        * (MAX_APPROXIMATION_OFFSET_M - MIN_APPROXIMATION_OFFSET_M)
    )

    # Destination point on a sphere, which also holds next to the poles.
    angular_distance = distance / EARTH_RADIUS_M
    origin_latitude = math.radians(latitude)
    approx_latitude = math.asin(
        math.sin(origin_latitude) * math.cos(angular_distance)
        + math.cos(origin_latitude) * math.sin(angular_distance) * math.cos(bearing)
    )
    approx_longitude = math.radians(longitude) + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(origin_latitude),
        math.cos(angular_distance)
        - math.sin(origin_latitude) * math.sin(approx_latitude),
    )
    return (
        math.degrees(approx_latitude),
        (math.degrees(approx_longitude) + 540) % 360 - 180,
    )


def resolve_location(
    event: Event,
    is_organizer: bool,
    participation_status: EventParticipantStatusEnum | None,
) -> EventLocationView:
    """Decide which location of an event a viewer receives.

    Only a PRIVATE event is restricted, and only its organizer and confirmed
    participants get the address. A pending request does not: asking to join
    must not be a shortcut to it. Pass `is_organizer=False` and no participation
    for a viewer without a session.
    """
    if (
        event.event_privacy is not EventPrivacyEnum.PRIVATE
        or is_organizer
        or participation_status is EventParticipantStatusEnum.CONFIRMED
    ):
        return EventLocationView(
            precision=LocationPrecisionEnum.EXACT,
            latitude=event.event_latitude,
            longitude=event.event_longitude,
            radius_m=None,
            label=event.location_name,
        )

    # Never fall back to `location_name`: it is the organizer's own text and
    # may be the full address.
    label = ", ".join(
        part for part in (event.location_neighborhood, event.location_city) if part
    )
    return EventLocationView(
        precision=LocationPrecisionEnum.APPROXIMATE,
        latitude=event.approx_latitude,
        longitude=event.approx_longitude,
        radius_m=settings.private_event_area_radius_m,
        label=label or None,
    )
