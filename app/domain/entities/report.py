__all__ = [
    "REPORT_DESCRIPTION_MAX_LENGTH",
    "NewReport",
    "Report",
    "ReportReason",
]

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import (
    ReportResolutionActionEnum,
    ReportScopeEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    ReportUnavailableReasonEnum,
)

REPORT_DESCRIPTION_MAX_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class NewReport:
    """A report as requested by its author, before it is persisted."""

    report_creator_id: UUID
    report_type: ReportTypeEnum
    description: str = ""
    reported_user_id: UUID | None = None
    reported_event_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Report:
    report_id: UUID | None
    report_creator_id: UUID
    report_type: ReportTypeEnum
    description: str
    created_at: datetime
    updated_at: datetime
    status: ReportStatusEnum = ReportStatusEnum.PENDING
    reported_user_id: UUID | None = None
    reported_event_id: UUID | None = None
    deleted_at: datetime | None = None
    resolved_by_id: UUID | None = None
    resolved_at: datetime | None = None
    resolution_action: ReportResolutionActionEnum | None = None


@dataclass(frozen=True, slots=True)
class ReportReason:
    code: ReportTypeEnum
    label: str
    scope: ReportScopeEnum = ReportScopeEnum.CONTENT
    available: bool = True
    unavailable_reason: ReportUnavailableReasonEnum | None = None
