from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import Event, EventParticipant
from app.domain.enums import EventParticipantStatusEnum, NotificationTypeEnum
from app.infrastructure.repository.models import EventModel, EventParticipantModel
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository


class SqlAlchemyParticipationRepository:
    def __init__(
        self, db: Session, notification_repo: SqlAlchemyNotificationRepository
    ) -> None:
        self.db = db
        self.notification_repo = notification_repo

    def get_event(self, event_id: UUID) -> Event | None:
        from app.infrastructure.repository.event import SqlAlchemyEventRepository

        model = self.db.scalar(
            select(EventModel).where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
        )
        return (
            SqlAlchemyEventRepository._to_entity(model) if model is not None else None
        )

    def get_existing_participant(
        self, event_id: UUID, user_id: UUID
    ) -> EventParticipant | None:
        model = self.db.scalar(
            select(EventParticipantModel).where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.user_id == user_id,
            )
        )
        return self._to_entity(model) if model is not None else None

    def get_organizer_id(self, event_id: UUID) -> UUID | None:
        return self.db.scalar(
            select(EventModel.event_creator_id).where(EventModel.event_id == event_id)
        )

    def join(
        self,
        event_id: UUID,
        user_id: UUID,
        status: EventParticipantStatusEnum,
    ) -> EventParticipant:
        model = EventParticipantModel(
            user_id=user_id,
            event_id=event_id,
            status=status,
        )
        self.db.add(model)
        self.db.flush()

        organizer_id = self.get_organizer_id(event_id)
        if organizer_id is not None and organizer_id != user_id:
            notification_type = (
                NotificationTypeEnum.EVENT_PARTICIPANT_JOINED
                if status is EventParticipantStatusEnum.CONFIRMED
                else NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST
            )
            self.notification_repo.notify_participant(
                recipient_id=organizer_id,
                participant_id=model.participant_id,
                type=notification_type,
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
