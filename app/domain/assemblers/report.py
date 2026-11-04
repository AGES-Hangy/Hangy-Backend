from app.domain.entities import Report
from app.presentation.dtos import ReportCreatedOutput


class ReportAssembler:
    @staticmethod
    def to_created_dto(report: Report) -> ReportCreatedOutput:
        assert report.report_id is not None
        return ReportCreatedOutput(
            report_id=report.report_id,
            report_type=report.report_type,
            status=report.status,
            created_at=report.created_at,
        )
