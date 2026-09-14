from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import ReportStatusEnum, ReportTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

if TYPE_CHECKING:
    from app.infrastructure.repository.models.event_model import EventModel
    from app.infrastructure.repository.models.user_model import UserModel


class ReportModel(Base):
    __tablename__ = "report"

    report_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_creator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.user_id", ondelete="CASCADE")
    )
    reported_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )
    reported_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("event.event_id", ondelete="SET NULL")
    )
    report_type: Mapped[ReportTypeEnum] = mapped_column(enum_column(ReportTypeEnum))
    description: Mapped[str] = mapped_column(String(1000))
    status: Mapped[ReportStatusEnum] = mapped_column(
        enum_column(ReportStatusEnum), default=ReportStatusEnum.PENDING
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    creator: Mapped[UserModel] = relationship(
        back_populates="created_reports", foreign_keys=[report_creator_id]
    )
    reported_user: Mapped[UserModel | None] = relationship(
        back_populates="received_reports", foreign_keys=[reported_user_id]
    )
    reported_event: Mapped[EventModel | None] = relationship(
        back_populates="reports", foreign_keys=[reported_event_id]
    )
