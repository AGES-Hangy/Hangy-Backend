from uuid import UUID

from app.domain.entities import NewReport
from app.domain.enums import ReportTypeEnum
from app.domain.services import InvalidReportReasonError
from app.presentation.dtos import ReportCreateInput


class ReportMapper:
    @staticmethod
    def to_new_report(dto: ReportCreateInput, creator_id: UUID) -> NewReport:
        try:
            report_type = ReportTypeEnum(dto.report_type)
        except ValueError as error:
            raise InvalidReportReasonError from error
        return NewReport(
            report_creator_id=creator_id,
            report_type=report_type,
            description=(dto.description or "").strip(),
            reported_user_id=dto.reported_user_id,
            reported_event_id=dto.reported_event_id,
        )