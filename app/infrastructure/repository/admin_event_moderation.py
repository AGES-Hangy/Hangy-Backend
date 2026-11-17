from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.entities import EventForModeration
from app.domain.enums import EventModerationStatusEnum, EventParticipantStatusEnum
from app.infrastructure.repository.models import EventModel, EventParticipantModel

__all__ = ["SqlAlchemyEventModerationRepository"]

_ACTIVE_PARTICIPATION_STATUSES = (
    EventParticipantStatusEnum.CONFIRMED,
    EventParticipantStatusEnum.PENDING,
)


class SqlAlchemyEventModerationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_for_moderation(self, event_id: UUID) -> EventForModeration | None:
        """Lock the row so two removals of the same event can't race.

        Unlike the public lookups this does not filter `deleted_at`: a removed
        event must still be found to answer "already removed".
        """
        model = self.db.scalar(
            select(EventModel).where(EventModel.event_id == event_id).with_for_update()
        )
        if model is None:
            return None
        return EventForModeration(
            event_id=model.event_id,
            event_creator_id=model.event_creator_id,
            event_title=model.event_title,
            moderation_status=model.moderation_status,
            deleted_at=model.deleted_at,
        )

    def remove(self, event_id: UUID, removed_at: datetime) -> None:
        """Soft delete for moderation.

        `deleted_at` is set as well so every existing active-event filter hides
        the event. Flush only: the caller commits.
        """
        model = self.db.scalar(
            select(EventModel).where(EventModel.event_id == event_id)
        )
        if model is None:
            raise ValueError("A removed event must already exist")
        model.moderation_status = EventModerationStatusEnum.REMOVED
        model.removed_at = removed_at
        model.deleted_at = removed_at
        self.db.flush()

    def cancel_active_participations(self, event_id: UUID) -> list[UUID]:
        """Cancel CONFIRMED/PENDING participations; return the affected user ids.

        Flush only: the caller commits.
        """
        user_ids = list(
            self.db.scalars(
                select(EventParticipantModel.user_id)
                .where(
                    EventParticipantModel.event_id == event_id,
                    EventParticipantModel.status.in_(_ACTIVE_PARTICIPATION_STATUSES),
                )
                .order_by(
                    EventParticipantModel.joined_at, EventParticipantModel.user_id
                )
            )
        )
        self.db.execute(
            update(EventParticipantModel)
            .where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.status.in_(_ACTIVE_PARTICIPATION_STATUSES),
            )
            .values(status=EventParticipantStatusEnum.CANCELLED)
        )
        self.db.flush()
        return user_ids

    def commit(self) -> None:
        self.db.commit()
