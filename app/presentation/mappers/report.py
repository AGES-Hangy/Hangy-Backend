from uuid import UUID

from app.domain.entities import NewReport
from app.presentation.dtos import ReportCreateInput


class ReportMapper:
    @staticmethod
    def to_new_report(dto: ReportCreateInput, creator_id: UUID) -> NewReport:
        return NewReport(
            report_creator_id=creator_id,
            report_type=dto.report_type,
            description=(dto.description or "").strip(),
            reported_user_id=dto.reported_user_id,
            reported_event_id=dto.reported_event_id,
        )
