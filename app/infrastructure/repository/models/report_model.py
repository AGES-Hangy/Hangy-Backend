from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    event,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, object_session, relationship

from app.domain.entities.report import REPORT_DESCRIPTION_MAX_LENGTH
from app.domain.enums import (
    ReportResolutionActionEnum,
    ReportStatusEnum,
    ReportTypeEnum,
)
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column

if TYPE_CHECKING:
    from app.infrastructure.repository.models.event_model import EventModel
    from app.infrastructure.repository.models.user_model import UserModel


class ReportModel(Base):
    __tablename__ = "report"
    __table_args__ = (
        CheckConstraint(
            "(reported_user_id IS NULL) <> (reported_event_id IS NULL)",
            name="ck_report_exactly_one_target",
        ),
        Index(
            "uq_report_pending_user",
            "report_creator_id",
            "reported_user_id",
            unique=True,
            postgresql_where=text(
                "status = 'PENDING' AND reported_user_id IS NOT NULL"
            ),
            sqlite_where=text("status = 'PENDING' AND reported_user_id IS NOT NULL"),
        ),
        Index(
            "uq_report_pending_event",
            "report_creator_id",
            "reported_event_id",
            unique=True,
            postgresql_where=text(
                "status = 'PENDING' AND reported_event_id IS NOT NULL"
            ),
            sqlite_where=text("status = 'PENDING' AND reported_event_id IS NOT NULL"),
        ),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_number: Mapped[int] = mapped_column(Integer, Identity(), unique=True)
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
    description: Mapped[str] = mapped_column(String(REPORT_DESCRIPTION_MAX_LENGTH))
    status: Mapped[ReportStatusEnum] = mapped_column(
        enum_column(ReportStatusEnum), default=ReportStatusEnum.PENDING
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the report was opened; updated_at moves on every status change.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    # Kept (as NULL) if the resolving admin's account is later deleted: the
    # resolution itself must survive.
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user.user_id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_action: Mapped[ReportResolutionActionEnum | None] = mapped_column(
        enum_column(ReportResolutionActionEnum)
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


@event.listens_for(ReportModel, "before_insert")
def _fill_report_number(mapper, connection, target: ReportModel) -> None:
    # Postgres numbers it through Identity; SQLite (tests) does not do that for
    # a column that is not the primary key.
    if target.report_number is not None or connection.dialect.name != "sqlite":
        return
    stored = connection.scalar(select(func.max(ReportModel.report_number))) or 0
    pending = (
        obj.report_number or 0
        for obj in object_session(target).new
        if isinstance(obj, ReportModel)
    )
    target.report_number = max(stored, *pending) + 1
