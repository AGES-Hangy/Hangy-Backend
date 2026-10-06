from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.entities import UserEvent
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    UserEventsTabEnum,
)
from app.infrastructure.repository.models import EventModel, EventParticipantModel


def _now_utc() -> datetime:
    return datetime.now(UTC)


class SqlAlchemyUserEventsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(
        self,
        user_id: UUID,
        tab: UserEventsTabEnum,
        *,
        limit: int,
        cursor_starts_at: datetime | None,
        cursor_event_id: UUID | None,
    ) -> list[UserEvent]:
        """List the user's confirmed participations of one profile tab.

        The tab rules mirror `get_profile_counts`, so a list never disagrees
        with the counter shown on its tab.
        """
        now = _now_utc()
        is_over = or_(
            EventModel.event_status == EventStatusEnum.FINISHED,
            EventModel.ends_at <= now,
        )

        stmt = (
            select(EventModel, EventParticipantModel.status)
            .join(
                EventParticipantModel,
                EventParticipantModel.event_id == EventModel.event_id,
            )
            .where(
                EventParticipantModel.user_id == user_id,
                EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
                EventModel.deleted_at.is_(None),
            )
        )

        if tab is UserEventsTabEnum.CONFIRMED:
            stmt = stmt.where(
                EventModel.event_status == EventStatusEnum.PUBLISHED, ~is_over
            ).order_by(EventModel.starts_at.asc(), EventModel.event_id.asc())
            if cursor_starts_at is not None and cursor_event_id is not None:
                stmt = stmt.where(
                    or_(
                        EventModel.starts_at > cursor_starts_at,
                        (EventModel.starts_at == cursor_starts_at)
                        & (EventModel.event_id > cursor_event_id),
                    )
                )
        else:
            stmt = stmt.where(
                EventModel.event_status.in_(
                    (EventStatusEnum.PUBLISHED, EventStatusEnum.FINISHED)
                ),
                is_over,
            ).order_by(EventModel.starts_at.desc(), EventModel.event_id.desc())
            if cursor_starts_at is not None and cursor_event_id is not None:
                stmt = stmt.where(
                    or_(
                        EventModel.starts_at < cursor_starts_at,
                        (EventModel.starts_at == cursor_starts_at)
                        & (EventModel.event_id < cursor_event_id),
                    )
                )

        rows = self.db.execute(stmt.limit(limit)).all()
        return [self._to_entity(event, status) for event, status in rows]

    @staticmethod
    def _to_entity(
        model: EventModel, participation_status: EventParticipantStatusEnum
    ) -> UserEvent:
        return UserEvent(
            event_id=model.event_id,
            title=model.event_title,
            starts_at=model.starts_at,
            participation_status=participation_status,
            location_name=model.location_name,
            cover_photo_url=model.cover_photo_url,
        )