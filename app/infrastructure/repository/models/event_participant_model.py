import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Enum as SQLEnum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.infrastructure.repository.base import Base
from app.domain.enums import EventParticipantStatusEnum

class EventParticipantModel(Base):
    __tablename__ = "event_participant"
    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_user_event_participant"),)

    participant_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False)
    event_id = Column(UUID(as_uuid=True), ForeignKey("event.event_id", ondelete="CASCADE"), nullable=False)
    status = Column(SQLEnum(EventParticipantStatusEnum), nullable=False)
    joined_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    event = relationship("EventModel", back_populates="participants")
    experiences = relationship("EventExperienceModel", back_populates="participant")