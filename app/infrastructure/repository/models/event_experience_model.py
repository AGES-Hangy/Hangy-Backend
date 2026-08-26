import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.infrastructure.repository.base import Base

class EventExperienceModel(Base):
    __tablename__ = "event_experience"

    experience_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_participant_id = Column(UUID(as_uuid=True), ForeignKey("event_participant.participant_id", ondelete="CASCADE"), nullable=False)
    description = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    participant = relationship("EventParticipantModel", back_populates="experiences")
    images = relationship("ExperienceImagesModel", back_populates="experience")