from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.entities import EventInviteLink, EventParticipant
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    NotificationTypeEnum,
)
from app.domain.services.invite import InviteAcceptance, InviteAcceptanceOutcome
from app.infrastructure.repository.models import (
    EventInviteLinkModel,
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    NotificationModel,
)


class SqlAlchemyInviteRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_token(self, token: str) -> EventInviteLink | None:
        model = self.db.scalar(
            select(EventInviteLinkModel).where(EventInviteLinkModel.token == token)
        )
        return self._invite_to_entity(model) if model is not None else None

    def accept(self, invite: EventInviteLink, user_id: UUID) -> InviteAcceptance:
        event = self.db.scalar(
            select(EventModel)
            .where(
                EventModel.event_id == invite.event_id,
                EventModel.deleted_at.is_(None),
                EventModel.event_status == EventStatusEnum.PUBLISHED,
            )
            .with_for_update()
        )
        if event is None:
            self.db.rollback()
            return InviteAcceptance(InviteAcceptanceOutcome.EVENT_NOT_FOUND)

        existing = self.db.scalar(
            select(EventParticipantModel).where(
                EventParticipantModel.event_id == event.event_id,
                EventParticipantModel.user_id == user_id,
            )
        )
        if existing is not None:
            self.db.rollback()
            return InviteAcceptance(InviteAcceptanceOutcome.PARTICIPANT_EXISTS)

        if event.max_participants is not None:
            confirmed_count = self.db.scalar(
                select(func.count(EventParticipantModel.participant_id)).where(
                    EventParticipantModel.event_id == event.event_id,
                    EventParticipantModel.status
                    == EventParticipantStatusEnum.CONFIRMED,
                )
            )
            if confirmed_count >= event.max_participants:
                self.db.rollback()
                return InviteAcceptance(InviteAcceptanceOutcome.EVENT_FULL)

        participant = EventParticipantModel(
            user_id=user_id,
            event_id=event.event_id,
            status=EventParticipantStatusEnum.CONFIRMED,
        )
        self.db.add(participant)
        self.db.flush()
        notification = NotificationModel(
            user_id=event.event_creator_id,
            type=NotificationTypeEnum.EVENT_PARTICIPANT_JOINED,
            read=False,
        )
        notification.participant_detail = EventParticipantNotificationModel(
            participant_id=participant.participant_id
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(participant)
        return InviteAcceptance(
            InviteAcceptanceOutcome.ACCEPTED, self._to_entity(participant)
        )

    @staticmethod
    def _invite_to_entity(model: EventInviteLinkModel) -> EventInviteLink:
        return EventInviteLink(
            invite_id=model.invite_id,
            event_id=model.event_id,
            token=model.token,
            created_by=model.created_by,
            created_at=model.created_at,
            expires_at=model.expires_at,
        )

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
