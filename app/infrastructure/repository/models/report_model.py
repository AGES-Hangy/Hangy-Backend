import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import relationship

from app.domain.enums import ReportStatusEnum, ReportTypeEnum
from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.types import enum_column


class ReportModel(Base):
    __tablename__ = "report"

    report_id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    report_creator_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False
    )
    reported_user_id = Column(
        Uuid, ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True
    )
    reported_event_id = Column(
        Uuid, ForeignKey("event.event_id", ondelete="SET NULL"), nullable=True
    )
    report_type = Column(enum_column(ReportTypeEnum), nullable=False)
    description = Column(String, nullable=False)
    status = Column(
        enum_column(ReportStatusEnum), nullable=False, default=ReportStatusEnum.PENDING
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    creator = relationship(
        "UserModel", back_populates="created_reports", foreign_keys=[report_creator_id]
    )
    reported_user = relationship(
        "UserModel", back_populates="received_reports", foreign_keys=[reported_user_id]
    )
    reported_event = relationship(
        "EventModel", back_populates="reports", foreign_keys=[reported_event_id]
    )
