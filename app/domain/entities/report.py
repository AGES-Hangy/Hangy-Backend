from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import ReportStatusEnum, ReportTypeEnum


@dataclass(frozen=True, slots=True)
class Report:
    report_id: UUID | None
    report_creator_id: UUID
    report_type: ReportTypeEnum
    description: str
    updated_at: datetime
    status: ReportStatusEnum = ReportStatusEnum.PENDING
    reported_user_id: UUID | None = None
    reported_event_id: UUID | None = None
    deleted_at: datetime | None = None
