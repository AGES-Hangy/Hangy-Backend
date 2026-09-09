from collections.abc import Collection
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.entities import Event, EventParticipant, NewEvent
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    NotificationTypeEnum,
)
from app.domain.services.event import EventIsFullError, EventParticipantNotFoundError
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    NotificationModel,
    TagModel,
)


class SqlAlchemyEventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def find_existing_tag_ids(self, tag_ids: Collection[UUID]) -> set[UUID]:
        if not tag_ids:
            return set()
        return set(
            self.db.scalars(
                select(TagModel.tag_id).where(TagModel.tag_id.in_(tag_ids))
            ).all()
        )

    def get_by_id(self, event_id: UUID) -> Event | None:
        model = self.db.scalar(
            select(EventModel).where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
        )
        return self._to_entity(model) if model is not None else None

    def get_participant(
        self, event_id: UUID, participant_id: UUID
    ) -> EventParticipant | None:
        model = self.db.scalar(
            select(EventParticipantModel).where(
                EventParticipantModel.participant_id == participant_id,
                EventParticipantModel.event_id == event_id,
            )
        )
        return self._to_participant_entity(model) if model is not None else None

    def update_participant_status_and_notify(
        self,
        event_id: UUID,
        participant_id: UUID,
        new_status: EventParticipantStatusEnum,
        notification_type: NotificationTypeEnum,
    ) -> EventParticipant:
        event_model = self.db.scalar(
            select(EventModel)
            .where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if event_model is None:
            # Fallback if event is not found
            event_model = self.db.scalar(
                select(EventModel).where(EventModel.event_id == event_id)
            )

        participant_model = self.db.scalar(
            select(EventParticipantModel)
            .where(
                EventParticipantModel.participant_id == participant_id,
                EventParticipantModel.event_id == event_id,
            )
            .with_for_update()
        )
        if participant_model is None:
            raise EventParticipantNotFoundError

        if new_status == EventParticipantStatusEnum.CONFIRMED:
            if event_model is not None and event_model.max_participants is not None:
                confirmed_count = (
                    self.db.scalar(
                        select(func.count(EventParticipantModel.participant_id)).where(
                            EventParticipantModel.event_id == event_id,
                            EventParticipantModel.status
                            == EventParticipantStatusEnum.CONFIRMED,
                        )
                    )
                    or 0
                )
                if confirmed_count >= event_model.max_participants:
                    raise EventIsFullError

        participant_model.status = new_status

        notification_model = NotificationModel(
            user_id=participant_model.user_id,
            type=notification_type,
            read=False,
        )
        self.db.add(notification_model)
        self.db.flush()

        participant_notification = EventParticipantNotificationModel(
            notification_id=notification_model.notification_id,
            participant_id=participant_model.participant_id,
        )
        self.db.add(participant_notification)

        self.db.commit()
        self.db.refresh(participant_model)
        return self._to_participant_entity(participant_model)

    def add(self, event: NewEvent) -> Event:
        model = EventModel(
            event_creator_id=event.event_creator_id,
            event_title=event.event_title,
            event_description=event.event_description,
            event_latitude=event.event_latitude,
            event_longitude=event.event_longitude,
            location_name=event.location_name,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            max_participants=event.max_participants,
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=event.event_privacy,
            cover_photo_url=event.cover_photo_url,
        )
        if event.tag_ids:
            model.tags = list(
                self.db.scalars(
                    select(TagModel).where(TagModel.tag_id.in_(event.tag_ids))
                ).all()
            )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: EventModel) -> Event:
        return Event(
            event_id=model.event_id,
            event_creator_id=model.event_creator_id,
            event_title=model.event_title,
            event_latitude=model.event_latitude,
            event_longitude=model.event_longitude,
            starts_at=model.starts_at,
            ends_at=model.ends_at,
            event_status=model.event_status,
            event_privacy=model.event_privacy,
            created_at=model.created_at,
            updated_at=model.updated_at,
            event_description=model.event_description,
            location_name=model.location_name,
            max_participants=model.max_participants,
            cover_photo_url=model.cover_photo_url,
            deleted_at=model.deleted_at,
        )

    @staticmethod
    def _to_participant_entity(model: EventParticipantModel) -> EventParticipant:
        return EventParticipant(
            participant_id=model.participant_id,
            user_id=model.user_id,
            event_id=model.event_id,
            status=model.status,
            joined_at=model.joined_at,
            updated_at=model.updated_at,
        )
