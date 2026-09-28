from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.domain.entities import Notification
from app.domain.enums import NotificationTypeEnum
from app.infrastructure.repository.models import (
    ConnectionNotificationModel,
    EventCancelledNotificationModel,
    EventParticipantNotificationModel,
    NotificationModel,
)


class SqlAlchemyNotificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def count_unread(self, user_id: UUID) -> int:
        return (
            self.db.scalar(
                select(func.count())
                .select_from(NotificationModel)
                .where(
                    NotificationModel.user_id == user_id,
                    NotificationModel.read.is_(False),
                )
            )
            or 0
        )

    def get_by_id(self, notification_id: UUID) -> Notification | None:
        model = self.db.get(NotificationModel, notification_id)
        return self._to_entity(model) if model is not None else None

    def mark_as_read(self, notification_id: UUID) -> None:
        self.db.execute(
            update(NotificationModel)
            .where(NotificationModel.notification_id == notification_id)
            .values(read=True)
        )
        self.db.commit()

    @staticmethod
    def _to_entity(model: NotificationModel) -> Notification:
        return Notification(
            notification_id=model.notification_id,
            user_id=model.user_id,
            type=model.type,
            created_at=model.created_at,
            read=model.read,
        )

    def notify_connection(
        self,
        recipient_id: UUID,
        connection_id: UUID,
        type: NotificationTypeEnum,
    ) -> None:
        notification = NotificationModel(user_id=recipient_id, type=type)
        self.db.add(notification)
        self.db.flush()
        self.db.add(
            ConnectionNotificationModel(
                notification_id=notification.notification_id,
                connection_id=connection_id,
            )
        )

    def notify_participant(
        self,
        recipient_id: UUID,
        participant_id: UUID,
        type: NotificationTypeEnum,
    ) -> None:
        notification = NotificationModel(user_id=recipient_id, type=type)
        self.db.add(notification)
        self.db.flush()
        self.db.add(
            EventParticipantNotificationModel(
                notification_id=notification.notification_id,
                participant_id=participant_id,
            )
        )

    def notify_event_cancelled(self, recipient_id: UUID, event_id: UUID) -> None:
        notification = NotificationModel(
            user_id=recipient_id, type=NotificationTypeEnum.EVENT_CANCELLED
        )
        self.db.add(notification)
        self.db.flush()
        self.db.add(
            EventCancelledNotificationModel(
                notification_id=notification.notification_id,
                event_id=event_id,
            )
        )

    def notify_event_updated(self, recipient_id: UUID, event_id: UUID) -> None:
        notification = NotificationModel(
            user_id=recipient_id, type=NotificationTypeEnum.EVENT_UPDATED
        )
        self.db.add(notification)
        self.db.flush()
        self.db.add(
            EventCancelledNotificationModel(
                notification_id=notification.notification_id,
                event_id=event_id,
            )
        )

    def mark_all_as_read(self, user_id: UUID) -> None:
        self.db.execute(
            update(NotificationModel)
            .where(
                NotificationModel.user_id == user_id,
                NotificationModel.read.is_(False),
            )
            .values(read=True)
        )
        self.db.commit()
