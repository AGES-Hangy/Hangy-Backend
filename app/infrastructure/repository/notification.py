from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

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
