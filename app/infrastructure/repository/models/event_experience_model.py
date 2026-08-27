import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import relationship

from app.infrastructure.repository.base import Base


class EventExperienceModel(Base):
    __tablename__ = "event_experience"

    experience_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    event_participant_id = Column(
        Uuid,
        ForeignKey("event_participant.participant_id", ondelete="CASCADE"),
        nullable=False,
    )
    description = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    participant = relationship("EventParticipantModel", back_populates="experiences")
    images = relationship(
        "ExperienceImagesModel", back_populates="experience", passive_deletes=True
    )
