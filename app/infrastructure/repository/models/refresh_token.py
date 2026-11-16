from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.repository.base import Base

__all__ = ["RefreshTokenModel"]


class RefreshTokenModel(Base):
    """One link of a refresh-token rotation chain (`family_id`).

    Only the SHA-256 of the opaque token is stored. Each refresh revokes the
    presented row and adds the next one to the same family; presenting a row
    that is already revoked means the token leaked, so the family is revoked.
    """

    __tablename__ = "refresh_token"
    __table_args__ = (Index("ix_refresh_token_user_id", "user_id"),)

    token_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE")
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
