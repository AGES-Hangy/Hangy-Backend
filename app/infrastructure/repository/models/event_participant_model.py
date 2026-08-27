import uuid

from sqlalchemy import Column, DateTime, ForeignKey, UniqueConstraint, Uuid, func
from sqlalchemy.orm import relationship

from app.domain.enums import EventParticipantStatusEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column


class EventParticipantModel(Base):
    __tablename__ = "event_participant"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_user_event_participant"),
    )

    participant_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False
    )
    event_id = Column(
        Uuid, ForeignKey("event.event_id", ondelete="CASCADE"), nullable=False
    )
    status = Column(enum_column(EventParticipantStatusEnum), nullable=False)
    joined_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("UserModel", back_populates="participations")
    event = relationship("EventModel", back_populates="participants")
    experiences = relationship(
        "EventExperienceModel", back_populates="participant", passive_deletes=True
    )
