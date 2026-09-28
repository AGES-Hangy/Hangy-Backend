from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.entities import Event, EventParticipant
from app.domain.enums import EventParticipantStatusEnum, NotificationTypeEnum
from app.infrastructure.repository.models import EventModel, EventParticipantModel
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository

NOTIFICATION_TYPE_BY_STATUS: dict[EventParticipantStatusEnum, NotificationTypeEnum] = {
    EventParticipantStatusEnum.CONFIRMED: (
        NotificationTypeEnum.EVENT_PARTICIPANT_JOINED
    ),
    EventParticipantStatusEnum.PENDING: (
        NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST
    ),
}


class SqlAlchemyParticipationRepository:
    def __init__(
        self, db: Session, notification_repo: SqlAlchemyNotificationRepository
    ) -> None:
        self.db = db
        self.notification_repo = notification_repo

    def get_event_for_update(self, event_id: UUID) -> Event | None:
        from app.infrastructure.repository.event import SqlAlchemyEventRepository

        model = self.db.scalar(
            select(EventModel)
            .where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        return (
            SqlAlchemyEventRepository._to_entity(model) if model is not None else None
        )

    def get_existing_participant_for_update(
        self, event_id: UUID, user_id: UUID
    ) -> EventParticipant | None:
        model = self.db.scalar(
            select(EventParticipantModel)
            .where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.user_id == user_id,
            )
            .with_for_update()
        )
        return self._to_entity(model) if model is not None else None

    def count_confirmed(self, event_id: UUID) -> int:
        return (
            self.db.scalar(
                select(func.count(EventParticipantModel.participant_id)).where(
                    EventParticipantModel.event_id == event_id,
                    EventParticipantModel.status
                    == EventParticipantStatusEnum.CONFIRMED,
                )
            )
            or 0
        )

    def upsert_participation(
        self,
        event_id: UUID,
        user_id: UUID,
        organizer_id: UUID,
        status: EventParticipantStatusEnum,
        existing_participant_id: UUID | None,
    ) -> EventParticipant:
        if existing_participant_id is not None:
            model = self.db.scalar(
                select(EventParticipantModel).where(
                    EventParticipantModel.participant_id == existing_participant_id
                )
            )
            if model is None:
                raise ValueError("A participant validated by the service must exist")
            model.status = status
            model.joined_at = datetime.now(UTC)
        else:
            model = EventParticipantModel(
                user_id=user_id, event_id=event_id, status=status
            )
            self.db.add(model)
            self.db.flush()

        if organizer_id != user_id:
            self.notification_repo.notify_participant(
                recipient_id=organizer_id,
                participant_id=model.participant_id,
                type=NOTIFICATION_TYPE_BY_STATUS[status],
            )

        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

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
