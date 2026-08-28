from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.repository.base import Base

if TYPE_CHECKING:
    from app.infrastructure.repository.models.event_experience_model import (
        EventExperienceModel,
    )


class ExperienceImagesModel(Base):
    __tablename__ = "experience_images"

    photo_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    experience_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_experience.experience_id", ondelete="CASCADE")
    )
    photo_url: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    experience: Mapped[EventExperienceModel] = relationship(back_populates="images")
