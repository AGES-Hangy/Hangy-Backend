from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import NotificationTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

if TYPE_CHECKING:
    from app.infrastructure.repository.models.event_model import EventModel
    from app.infrastructure.repository.models.event_participant_model import (
        EventParticipantModel,
    )
    from app.infrastructure.repository.models.user_connection_model import (
        UserConnectionModel,
    )
    from app.infrastructure.repository.models.user_model import UserModel


class NotificationModel(Base):
    __tablename__ = "notification"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE")
    )
    type: Mapped[NotificationTypeEnum] = mapped_column(
        enum_column(NotificationTypeEnum)
    )
    read: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=func.false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[UserModel] = relationship(back_populates="notifications")
    connection_detail: Mapped[ConnectionNotificationModel | None] = relationship(
        back_populates="notification",
        passive_deletes=True,
    )
    participant_detail: Mapped[EventParticipantNotificationModel | None] = (
        relationship(
            back_populates="notification",
            passive_deletes=True,
        )
    )
    event_cancelled_detail: Mapped[EventCancelledNotificationModel | None] = (
        relationship(
            back_populates="notification",
            passive_deletes=True,
        )
    )


class ConnectionNotificationModel(Base):
    __tablename__ = "connection_notification"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification.notification_id", ondelete="CASCADE"),
        primary_key=True,
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_connection.connection_id", ondelete="CASCADE")
    )

    notification: Mapped[NotificationModel] = relationship(
        back_populates="connection_detail"
    )
    connection: Mapped[UserConnectionModel] = relationship()


class EventParticipantNotificationModel(Base):
    __tablename__ = "event_participant_notification"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification.notification_id", ondelete="CASCADE"),
        primary_key=True,
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_participant.participant_id", ondelete="CASCADE")
    )

    notification: Mapped[NotificationModel] = relationship(
        back_populates="participant_detail"
    )
    participant: Mapped[EventParticipantModel] = relationship()


class EventCancelledNotificationModel(Base):
    __tablename__ = "event_cancelled_notification"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification.notification_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event.event_id", ondelete="CASCADE")
    )

    notification: Mapped[NotificationModel] = relationship(
        back_populates="event_cancelled_detail"
    )
    event: Mapped[EventModel] = relationship()
