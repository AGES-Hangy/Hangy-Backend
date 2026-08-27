import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import relationship

from app.infrastructure.repository.base import Base


class ExperienceImagesModel(Base):
    __tablename__ = "experience_images"

    photo_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    experience_id = Column(
        Uuid,
        ForeignKey("event_experience.experience_id", ondelete="CASCADE"),
        nullable=False,
    )
    photo_url = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    experience = relationship("EventExperienceModel", back_populates="images")
