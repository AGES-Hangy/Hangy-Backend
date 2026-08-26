import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from app.infrastructure.repository.base import Base

class ExperienceImagesModel(Base):
    __tablename__ = "experience_images"

    photo_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experience_id = Column(UUID(as_uuid=True), ForeignKey("event_experience.experience_id", ondelete="CASCADE"), nullable=False)
    photo_url = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    experience = relationship("EventExperienceModel", back_populates="images")