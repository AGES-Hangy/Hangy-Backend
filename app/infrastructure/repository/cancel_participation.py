from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import Event, EventParticipant
from app.domain.enums import EventParticipantStatusEnum
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import EventModel, EventParticipantModel

__all__ = ["SqlAlchemyCancelParticipationRepository"]


class SqlAlchemyCancelParticipationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_event_for_update(self, event_id: UUID) -> Event | None:
        model = self.db.scalar(
            select(EventModel)
            .where(EventModel.event_id == event_id, EventModel.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return SqlAlchemyEventRepository._to_entity(model) if model else None

    def get_participant_for_update(
        self, event_id: UUID, user_id: UUID
    ) -> EventParticipant | None:
        model = self.db.scalar(
            select(EventParticipantModel)
            .where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._to_entity(model) if model else None

    def cancel(self, event_id: UUID, user_id: UUID) -> None:
        model = self.db.scalar(
            select(EventParticipantModel).where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.user_id == user_id,
            )
        )
        if model is None:
            raise ValueError("A participant validated by the service must exist")
        model.status = EventParticipantStatusEnum.CANCELLED
        model.updated_at = datetime.now(UTC)
        # Keep the row and joined_at for history/rejoining; no notification.
        self.db.commit()

    @staticmethod
    def _to_entity(model: EventParticipantModel) -> EventParticipant:
        return EventParticipant(
            participant_id=model.participant_id,
            user_id=model.user_id,
            event_id=model.event_id,
            status=model.status,
            joined_at=model.joined_at,
            updated_at=model.updated_at,
        )
