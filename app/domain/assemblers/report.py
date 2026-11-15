__all__ = ["ReportAssembler"]

from app.domain.entities import Report, ReportReason
from app.presentation.dtos import ReportCreatedOutput, ReportReasonOutput


class ReportAssembler:
    """Build report response DTOs from domain entities."""

    @staticmethod
    def to_reason_dto(reason: ReportReason) -> ReportReasonOutput:
        return ReportReasonOutput(
            code=reason.code,
            label=reason.label,
            scope=reason.scope,
            available=reason.available,
            unavailable_reason=reason.unavailable_reason,
        )

    @staticmethod
    def to_reason_dtos(reasons: list[ReportReason]) -> list[ReportReasonOutput]:
        return [ReportAssembler.to_reason_dto(reason) for reason in reasons]

    @staticmethod
    def to_created_dto(report: Report) -> ReportCreatedOutput:
        assert report.report_id is not None
        return ReportCreatedOutput(
            report_id=report.report_id,
            report_type=report.report_type,
            status=report.status,
            created_at=report.created_at,
        )
