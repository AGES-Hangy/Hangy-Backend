from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.repository.base import Base

if TYPE_CHECKING:
    from app.infrastructure.repository.models.event_participant_model import (
        EventParticipantModel,
    )
    from app.infrastructure.repository.models.experience_images_model import (
        ExperienceImagesModel,
    )


class EventExperienceModel(Base):
    __tablename__ = "event_experience"

    experience_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    event_participant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_participant.participant_id", ondelete="CASCADE")
    )
    description: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    participant: Mapped[EventParticipantModel] = relationship(
        back_populates="experiences"
    )
    images: Mapped[list[ExperienceImagesModel]] = relationship(
        back_populates="experience", passive_deletes=True
    )
