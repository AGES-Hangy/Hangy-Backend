"""SQLAlchemy repository for notifications — write side + read/list side."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.domain.entities import Notification
from app.domain.enums import NotificationTypeEnum
from app.infrastructure.repository.models import (
    ConnectionNotificationModel,
    EventCancelledNotificationModel,
    EventParticipantNotificationModel,
    NotificationModel,
)
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.event_participant_model import (
    EventParticipantModel,
)
from app.infrastructure.repository.models.user_connection_model import (
    UserConnectionModel,
)
from app.infrastructure.repository.models.user_model import UserModel


class SqlAlchemyNotificationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Write helpers (called by other services — US6.2+)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Read side
    # ------------------------------------------------------------------

    def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_id: UUID | None,
        unread_only: bool,
    ) -> list[Notification]:
        stmt = (
            select(NotificationModel)
            .where(NotificationModel.user_id == user_id)
            .options(
                joinedload(NotificationModel.connection_detail).joinedload(
                    ConnectionNotificationModel.connection
                ),
                joinedload(NotificationModel.participant_detail).joinedload(
                    EventParticipantNotificationModel.participant
                ),
                joinedload(NotificationModel.event_cancelled_detail).joinedload(
                    EventCancelledNotificationModel.event
                ),
            )
            .order_by(
                NotificationModel.created_at.desc(),
                NotificationModel.notification_id.desc(),
            )
            .limit(limit)
        )

        if unread_only:
            stmt = stmt.where(NotificationModel.read.is_(False))

        if cursor_created_at is not None and cursor_id is not None:
            stmt = stmt.where(
                (NotificationModel.created_at < cursor_created_at)
                | (
                    (NotificationModel.created_at == cursor_created_at)
                    & (NotificationModel.notification_id < cursor_id)
                )
            )

        rows = self.db.scalars(stmt).unique().all()
        return [self._to_entity(row) for row in rows]

    def count_unread(self, user_id: UUID) -> int:
        result = self.db.scalar(
            select(func.count()).where(
                NotificationModel.user_id == user_id,
                NotificationModel.read.is_(False),
            )
        )
        return result or 0

    def mark_as_read(self, notification_id: UUID, user_id: UUID) -> bool:
        result = self.db.execute(
            update(NotificationModel)
            .where(
                NotificationModel.notification_id == notification_id,
                NotificationModel.user_id == user_id,
            )
            .values(read=True)
        )
        self.db.commit()
        return result.rowcount > 0

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

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _to_entity(model: NotificationModel) -> Notification:
        payload = _build_payload(model)
        return Notification(
            notification_id=model.notification_id,
            user_id=model.user_id,
            type=model.type,
            read=model.read,
            created_at=model.created_at,
            payload=payload,
        )


def _build_payload(model: NotificationModel) -> dict:
    """Build a flat payload dict regardless of which subtable holds the data."""
    t = model.type

    # Connection notifications
    if t in (
        NotificationTypeEnum.CONNECTION_REQUEST,
        NotificationTypeEnum.CONNECTION_ACCEPTED,
    ):
        if model.connection_detail and model.connection_detail.connection:
            conn: UserConnectionModel = model.connection_detail.connection
            # The sender is the other party: requester for REQUEST, receiver
            # for ACCEPTED (seen from the notification recipient's perspective).
            sender: UserModel = (
                conn.requester
                if t == NotificationTypeEnum.CONNECTION_REQUEST
                else conn.receiver
            )
            return {
                "connection_id": str(conn.connection_id),
                "sender": {
                    "id": str(sender.user_id),
                    "name": sender.name or "",
                },
            }
        return {}

    # Event-participant notifications (request, approved, rejected, etc.)
    _PARTICIPANT_TYPES = {
        NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
        NotificationTypeEnum.EVENT_REQUEST_APPROVED,
        NotificationTypeEnum.EVENT_REQUEST_REJECTED,
        NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED,
        NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED,
        NotificationTypeEnum.EVENT_PARTICIPANT_JOINED,
        NotificationTypeEnum.EVENT_STARTING_SOON,
    }
    if t in _PARTICIPANT_TYPES:
        if model.participant_detail and model.participant_detail.participant:
            ep: EventParticipantModel = model.participant_detail.participant
            event: EventModel = ep.event
            sender_user: UserModel = ep.user
            return {
                "event_id": str(event.event_id),
                "event_title": event.event_title,
                "sender": {
                    "id": str(sender_user.user_id),
                    "name": sender_user.name or "",
                },
            }
        return {}

    # Event-cancelled / event-updated notifications
    if t in (
        NotificationTypeEnum.EVENT_CANCELLED,
        NotificationTypeEnum.EVENT_UPDATED,
    ):
        if model.event_cancelled_detail and model.event_cancelled_detail.event:
            ev: EventModel = model.event_cancelled_detail.event
            return {
                "event_id": str(ev.event_id),
                "event_title": ev.event_title,
            }
        return {}

    return {}
