from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.domain.entities import NearbyEvent
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)
from app.infrastructure.repository.block import block_exists_between
from app.infrastructure.repository.models import EventModel, EventParticipantModel

EARTH_RADIUS_M = 6_371_000
METERS_PER_DEGREE = 111_320


class SqlAlchemyNearbyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_nearby(
        self,
        viewer_id: UUID,
        latitude: float,
        longitude: float,
        radius_m: int,
        limit: int,
    ) -> list[NearbyEvent]:
        latitude_delta = radius_m / METERS_PER_DEGREE
        min_latitude = max(-90.0, latitude - latitude_delta)
        max_latitude = min(90.0, latitude + latitude_delta)

        if abs(latitude) >= 89.9:
            longitude_filter = True
        else:
            longitude_delta = radius_m / (METERS_PER_DEGREE * cos(radians(latitude)))
            min_longitude = longitude - longitude_delta
            max_longitude = longitude + longitude_delta
            if min_longitude < -180.0:
                longitude_filter = or_(
                    EventModel.event_longitude >= min_longitude + 360,
                    EventModel.event_longitude <= max_longitude,
                )
            elif max_longitude > 180.0:
                longitude_filter = or_(
                    EventModel.event_longitude >= min_longitude,
                    EventModel.event_longitude <= max_longitude - 360,
                )
            else:
                longitude_filter = EventModel.event_longitude.between(
                    min_longitude, max_longitude
                )

        participants_count = (
            select(func.count(EventParticipantModel.participant_id))
            .where(
                EventParticipantModel.event_id == EventModel.event_id,
                EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
            )
            .correlate(EventModel)
            .scalar_subquery()
        )
        is_confirmed = exists().where(
            EventParticipantModel.event_id == EventModel.event_id,
            EventParticipantModel.user_id == viewer_id,
            EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
        )
        statement = select(EventModel, participants_count, is_confirmed).where(
            EventModel.deleted_at.is_(None),
            EventModel.event_status == EventStatusEnum.PUBLISHED,
            EventModel.starts_at > datetime.now(UTC),
            EventModel.event_privacy.in_(
                (EventPrivacyEnum.PUBLIC, EventPrivacyEnum.PRIVATE)
            ),
            EventModel.event_latitude.between(min_latitude, max_latitude),
            longitude_filter,
            ~block_exists_between(EventModel.event_creator_id, viewer_id),
        )
        rows = self.db.execute(statement).all()

        nearby: list[NearbyEvent] = []
        for event, count, confirmed in rows:
            distance_m = _distance_m(
                latitude,
                longitude,
                event.event_latitude,
                event.event_longitude,
            )
            if distance_m <= radius_m:
                nearby.append(
                    NearbyEvent(
                        event_id=event.event_id,
                        title=event.event_title,
                        event_date=event.starts_at,
                        latitude=event.event_latitude,
                        longitude=event.event_longitude,
                        location_name=event.location_name,
                        cover_photo_url=event.cover_photo_url,
                        distance_m=distance_m,
                        participants_count=count or 0,
                        is_confirmed=bool(confirmed),
                        privacy=event.event_privacy,
                    )
                )

        nearby.sort(key=lambda item: (item.distance_m, item.event_id))
        return nearby[:limit]


def _distance_m(
    origin_latitude: float,
    origin_longitude: float,
    event_latitude: float,
    event_longitude: float,
) -> int:
    latitude_delta = radians(event_latitude - origin_latitude)
    longitude_delta = radians(event_longitude - origin_longitude)
    origin_latitude = radians(origin_latitude)
    event_latitude = radians(event_latitude)
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(origin_latitude) * cos(event_latitude) * sin(longitude_delta / 2) ** 2
    )
    return round(2 * EARTH_RADIUS_M * asin(sqrt(haversine)))
