from datetime import UTC, datetime
from math import cos, radians
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.domain.entities import NearbyEventCandidate
from app.domain.enums import EventParticipantStatusEnum
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import EventModel, EventParticipantModel
from app.infrastructure.repository.search import visible_events_filter

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
    ) -> list[NearbyEventCandidate]:
        latitude_delta = radius_m / METERS_PER_DEGREE
        min_latitude = max(-90.0, latitude - latitude_delta)
        max_latitude = min(90.0, latitude + latitude_delta)

        def coordinate_filter(latitude_column, longitude_column):
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
                longitude_filter = longitude_column.between(
                    min_longitude, max_longitude
                )
            return and_(latitude_filter, longitude_filter)

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
        rows = self.db.execute(statement).all()
        return [
            NearbyEventCandidate(
                event=SqlAlchemyEventRepository.to_entity(event),
                participants_count=count or 0,
                viewer_participation_status=participation_status,
            )
            for event, count, participation_status in rows
        ]
