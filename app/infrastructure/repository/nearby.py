from collections.abc import Collection
from datetime import UTC, datetime
from math import cos, radians
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.domain.entities import NearbyEventCandidate
from app.domain.enums import EventParticipantStatusEnum
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
)
from app.infrastructure.repository.models.event_model import event_tag
from app.infrastructure.repository.search import visible_events_filter

METERS_PER_DEGREE = 111_320


def bounding_box_filter(
    latitude_column: Any,
    longitude_column: Any,
    latitude: float,
    longitude: float,
    radius_m: int,
) -> ColumnElement[bool]:
    """Square around the point that holds every coordinate within `radius_m`.

    Cheap and index-friendly (`idx_event_*coordinates`), but its corners reach
    past the radius: pair it with `within_radius_filter` for a real circle.
    """
    latitude_delta = radius_m / METERS_PER_DEGREE
    min_latitude = max(-90.0, latitude - latitude_delta)
    max_latitude = min(90.0, latitude + latitude_delta)
    latitude_filter = latitude_column.between(min_latitude, max_latitude)
    if abs(latitude) >= 89.9:
        return latitude_filter
    longitude_delta = radius_m / (METERS_PER_DEGREE * cos(radians(latitude)))
    min_longitude = longitude - longitude_delta
    max_longitude = longitude + longitude_delta
    if min_longitude < -180.0:
        longitude_filter = or_(
            longitude_column >= min_longitude + 360,
            longitude_column <= max_longitude,
        )
    elif max_longitude > 180.0:
        longitude_filter = or_(
            longitude_column >= min_longitude,
            longitude_column <= max_longitude - 360,
        )
    else:
        longitude_filter = longitude_column.between(min_longitude, max_longitude)
    return and_(latitude_filter, longitude_filter)


def within_radius_filter(
    latitude_column: Any,
    longitude_column: Any,
    latitude: float,
    longitude: float,
    radius_m: int,
) -> ColumnElement[bool]:
    """Coordinates within `radius_m` of the point, computed in SQL.

    Equirectangular distance: only arithmetic, so SQLite and PostgreSQL agree,
    and a few percent off the great circle at the feed's few hundred km.
    """
    longitude_scale = cos(radians(latitude))
    raw_longitude_delta = longitude_column - longitude
    # Shortest way around the antimeridian.
    longitude_delta = case(
        (raw_longitude_delta > 180, raw_longitude_delta - 360),
        (raw_longitude_delta < -180, raw_longitude_delta + 360),
        else_=raw_longitude_delta,
    )
    latitude_delta = latitude_column - latitude
    radius_degrees = radius_m / METERS_PER_DEGREE
    return and_(
        bounding_box_filter(
            latitude_column, longitude_column, latitude, longitude, radius_m
        ),
        latitude_delta * latitude_delta
        + longitude_delta * longitude_delta * (longitude_scale * longitude_scale)
        <= radius_degrees * radius_degrees,
    )


class SqlAlchemyNearbyRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_nearby(
        self,
        viewer_id: UUID,
        latitude: float,
        longitude: float,
        radius_m: int,
        starts_from: datetime | None = None,
        starts_until: datetime | None = None,
        tag_ids: Collection[UUID] | None = None,
    ) -> list[NearbyEventCandidate]:
        def coordinate_filter(latitude_column, longitude_column):
            return bounding_box_filter(
                latitude_column, longitude_column, latitude, longitude, radius_m
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
        viewer_participation = aliased(EventParticipantModel)
        statement = (
            select(EventModel, participants_count, viewer_participation.status)
            .outerjoin(
                viewer_participation,
                and_(
                    viewer_participation.event_id == EventModel.event_id,
                    viewer_participation.user_id == viewer_id,
                ),
            )
            .where(
                *visible_events_filter(viewer_id, datetime.now(UTC)),
                or_(
                    coordinate_filter(
                        EventModel.event_latitude, EventModel.event_longitude
                    ),
                    coordinate_filter(
                        EventModel.approx_latitude, EventModel.approx_longitude
                    ),
                ),
            )
        )
        if starts_from is not None:
            statement = statement.where(EventModel.starts_at >= starts_from)
        if starts_until is not None:
            statement = statement.where(EventModel.starts_at <= starts_until)
        if tag_ids is not None:
            statement = statement.where(
                EventModel.event_id.in_(
                    select(event_tag.c.event_id).where(event_tag.c.tag_id.in_(tag_ids))
                )
            )
        rows = self.db.execute(statement).all()
        return [
            NearbyEventCandidate(
                event=SqlAlchemyEventRepository.to_entity(event),
                participants_count=count or 0,
                viewer_participation_status=participation_status,
            )
            for event, count, participation_status in rows
        ]

    def expand_tag_ids(self, tag_ids: Collection[UUID]) -> set[UUID]:
        found = set(
            self.db.scalars(
                select(TagModel.tag_id).where(TagModel.tag_id.in_(tag_ids))
            ).all()
        )
        # The tree is shallow (macro -> micro), so one query per level is enough.
        frontier = found
        while frontier:
            children = set(
                self.db.scalars(
                    select(TagModel.tag_id).where(TagModel.tag_parent_id.in_(frontier))
                ).all()
            )
            frontier = children - found
            found |= frontier
        return found
