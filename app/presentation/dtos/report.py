from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.entities import REPORT_DESCRIPTION_MAX_LENGTH
from app.domain.enums import ReportStatusEnum, ReportTypeEnum


class ReportCreateInput(BaseModel):
    report_type: str = Field(max_length=50)
    reported_user_id: UUID | None = None
    reported_event_id: UUID | None = None
    description: str | None = Field(
        default=None, max_length=REPORT_DESCRIPTION_MAX_LENGTH
    )


class ReportCreatedOutput(BaseModel):
    """The author is deliberately absent: a report is never traced back."""

    report_id: UUID
    report_type: ReportTypeEnum
    status: ReportStatusEnum
    created_at: datetime
