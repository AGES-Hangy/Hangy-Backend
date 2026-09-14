from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import EventParticipantStatusEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

if TYPE_CHECKING:
    from app.infrastructure.repository.models.event_experience_model import (
        EventExperienceModel,
    )
    from app.infrastructure.repository.models.event_model import EventModel
    from app.infrastructure.repository.models.user_model import UserModel


class EventParticipantModel(Base):
    __tablename__ = "event_participant"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_user_event_participant"),
    )

    participant_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE")
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event.event_id", ondelete="CASCADE")
    )
    status: Mapped[EventParticipantStatusEnum] = mapped_column(
        enum_column(EventParticipantStatusEnum)
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[UserModel] = relationship(back_populates="participations")
    event: Mapped[EventModel] = relationship(back_populates="participants")
    experiences: Mapped[list[EventExperienceModel]] = relationship(
        back_populates="participant", passive_deletes=True
    )
