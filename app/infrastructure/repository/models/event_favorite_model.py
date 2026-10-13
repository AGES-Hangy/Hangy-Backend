from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.repository.base import Base


class EventFavoriteModel(Base):
    __tablename__ = "event_favorite"
    __table_args__ = (
        # The primary key already leads with user_id; this one serves the
        # lookups (and cascades) that start from the event.
        Index("idx_event_favorite_event_id", "event_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event.event_id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
