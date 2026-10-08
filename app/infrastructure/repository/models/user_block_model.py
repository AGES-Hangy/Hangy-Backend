from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.repository.base import Base

if TYPE_CHECKING:
    from app.infrastructure.repository.models.user_model import UserModel


class UserBlockModel(Base):
    __tablename__ = "user_block"
    __table_args__ = (
        CheckConstraint("blocker_id <> blocked_id", name="ck_user_block_not_self"),
        Index("ix_user_block_blocked_id", "blocked_id"),
    )

    blocker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    blocker: Mapped[UserModel] = relationship(foreign_keys=[blocker_id])
    blocked: Mapped[UserModel] = relationship(foreign_keys=[blocked_id])
