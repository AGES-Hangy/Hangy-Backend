import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Uuid, func
from sqlalchemy.orm import relationship

from app.domain.enums import NotificationTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column


class NotificationModel(Base):
    __tablename__ = "notification"

    notification_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False
    )
    type = Column(enum_column(NotificationTypeEnum), nullable=False)
    read = Column(Boolean, nullable=False, default=False, server_default=func.false())
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user = relationship("UserModel", back_populates="notifications")
    connection_detail = relationship(
        "ConnectionNotificationModel",
        back_populates="notification",
        uselist=False,
        passive_deletes=True,
    )
    participant_detail = relationship(
        "EventParticipantNotificationModel",
        back_populates="notification",
        uselist=False,
        passive_deletes=True,
    )
    event_cancelled_detail = relationship(
        "EventCancelledNotificationModel",
        back_populates="notification",
        uselist=False,
        passive_deletes=True,
    )


class ConnectionNotificationModel(Base):
    __tablename__ = "connection_notification"

    notification_id = Column(
        Uuid,
        ForeignKey("notification.notification_id", ondelete="CASCADE"),
        primary_key=True,
    )
    connection_id = Column(
        Uuid,
        ForeignKey("user_connection.connection_id", ondelete="CASCADE"),
        nullable=False,
    )

    notification = relationship("NotificationModel", back_populates="connection_detail")
    connection = relationship("UserConnectionModel")


class EventParticipantNotificationModel(Base):
    __tablename__ = "event_participant_notification"

    notification_id = Column(
        Uuid,
        ForeignKey("notification.notification_id", ondelete="CASCADE"),
        primary_key=True,
    )
    participant_id = Column(
        Uuid,
        ForeignKey("event_participant.participant_id", ondelete="CASCADE"),
        nullable=False,
    )

    notification = relationship(
        "NotificationModel", back_populates="participant_detail"
    )
    participant = relationship("EventParticipantModel")


class EventCancelledNotificationModel(Base):
    __tablename__ = "event_cancelled_notification"

    notification_id = Column(
        Uuid,
        ForeignKey("notification.notification_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id = Column(
        Uuid, ForeignKey("event.event_id", ondelete="CASCADE"), nullable=False
    )

    notification = relationship(
        "NotificationModel", back_populates="event_cancelled_detail"
    )
    event = relationship("EventModel")
