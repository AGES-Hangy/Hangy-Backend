from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.repository.base import Base

if TYPE_CHECKING:
    from app.infrastructure.repository.models.event_model import EventModel


class EventInviteLinkModel(Base):
    __tablename__ = "event_invite_link"

    invite_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event.event_id", ondelete="CASCADE")
    )
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    event: Mapped[EventModel] = relationship(back_populates="invite_links")
