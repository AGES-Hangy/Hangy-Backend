from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import Event
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    NotificationTypeEnum,
)
from app.infrastructure.repository.models import (
    EventCancelledNotificationModel,
    EventModel,
    EventParticipantModel,
    NotificationModel,
)


class SqlAlchemyEventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, event_id: UUID) -> Event | None:
        model = self.db.scalar(
            select(EventModel).where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
        )
        return self._to_entity(model) if model is not None else None

    def cancel(self, event_id: UUID) -> Event:
        model = self.db.scalar(
            select(EventModel).where(EventModel.event_id == event_id)
        )
        if model is None:
            raise ValueError("An event validated by the service must exist")

        model.event_status = EventStatusEnum.CANCELLED
        model.updated_at = datetime.now(UTC)
        participant_user_ids = self.db.scalars(
            select(EventParticipantModel.user_id).where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.status.in_(
                    (
                        EventParticipantStatusEnum.CONFIRMED,
                        EventParticipantStatusEnum.PENDING,
                    )
                ),
            )
        ).all()
        for user_id in participant_user_ids:
            notification = NotificationModel(
                user_id=user_id,
                type=NotificationTypeEnum.EVENT_CANCELLED,
            )
            notification.event_cancelled_detail = EventCancelledNotificationModel(
                event_id=event_id
            )
            self.db.add(notification)
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: EventModel) -> Event:
        return Event(
            event_id=model.event_id,
            event_creator_id=model.event_creator_id,
            event_title=model.event_title,
            event_description=model.event_description,
            event_latitude=model.event_latitude,
            event_longitude=model.event_longitude,
            starts_at=model.starts_at,
            ends_at=model.ends_at,
            max_participants=model.max_participants,
            event_status=model.event_status,
            event_privacy=model.event_privacy,
            cover_photo_url=model.cover_photo_url,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )
