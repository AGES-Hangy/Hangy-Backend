from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import UserConnectionStatusEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

if TYPE_CHECKING:
    from app.infrastructure.repository.models.user_model import UserModel


class UserConnectionModel(Base):
    __tablename__ = "user_connection"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE")
    )
    receiver_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE")
    )
    status: Mapped[UserConnectionStatusEnum] = mapped_column(
        enum_column(UserConnectionStatusEnum)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requester: Mapped[UserModel] = relationship(
        back_populates="sent_connections", foreign_keys=[requester_id]
    )
    receiver: Mapped[UserModel] = relationship(
        back_populates="received_connections", foreign_keys=[receiver_id]
    )
