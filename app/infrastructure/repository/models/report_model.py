import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.infrastructure.repository.base import Base
from app.domain.enums import ReportTypeEnum, ReportStatusEnum

class ReportModel(Base):
    __tablename__ = "report"

    report_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_creator_id = Column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="CASCADE"), nullable=False)
    reported_user_id = Column(UUID(as_uuid=True), ForeignKey("user.user_id", ondelete="SET NULL"), nullable=True)
    reported_event_id = Column(UUID(as_uuid=True), ForeignKey("event.event_id", ondelete="SET NULL"), nullable=True)
    report_type = Column(SQLEnum(ReportTypeEnum), nullable=False)
    description = Column(String, nullable=False)
    status = Column(SQLEnum(ReportStatusEnum), nullable=False, default=ReportStatusEnum.PENDING)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )