import uuid
from sqlalchemy import Column, Boolean, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.infrastructure.repository.base import Base
from app.domain.enums import NotificationTypeEnum

class NotificationModel(Base):
    __tablename__ = "notification"

    notification_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False)
    type = Column(SQLEnum(NotificationTypeEnum), nullable=False)
    read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

class ConnectionNotificationModel(Base):
    __tablename__ = "connection_notification"

    notification_id = Column(UUID(as_uuid=True), ForeignKey("notification.notification_id", ondelete="CASCADE"), primary_key=True)
    connection_id = Column(UUID(as_uuid=True), ForeignKey("user_connection.connection_id", ondelete="CASCADE"), nullable=False)

class EventInviteNotificationModel(Base):
    __tablename__ = "event_invite_notification"

    notification_id = Column(UUID(as_uuid=True), ForeignKey("notification.notification_id", ondelete="CASCADE"), primary_key=True)
    event_id = Column(UUID(as_uuid=True), ForeignKey("event.event_id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False)

class EventParticipantNotificationModel(Base):
    __tablename__ = "event_participant_notification"

    notification_id = Column(UUID(as_uuid=True), ForeignKey("notification.notification_id", ondelete="CASCADE"), primary_key=True)
    participant_id = Column(UUID(as_uuid=True), ForeignKey("event_participant.participant_id", ondelete="CASCADE"), nullable=False)

class EventCancelledNotificationModel(Base):
    __tablename__ = "event_cancelled_notification"

    notification_id = Column(UUID(as_uuid=True), ForeignKey("notification.notification_id", ondelete="CASCADE"), primary_key=True)
    event_id = Column(UUID(as_uuid=True), ForeignKey("event.event_id", ondelete="CASCADE"), nullable=False)