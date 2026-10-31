__all__ = ["AdminReportAssembler"]

from app.domain.entities import AdminReportDetail, AdminReportResolution
from app.presentation.dtos.admin_report import (
    AdminReportDetailOutput,
    AdminReportPreviousReportsOutput,
    AdminReportResolutionOutput,
    AdminReportTargetOutput,
    AdminReportUserOutput,
)


class AdminReportAssembler:
    @staticmethod
    def to_detail_dto(detail: AdminReportDetail) -> AdminReportDetailOutput:
        target = detail.target
        previous = detail.previous_reports
        return AdminReportDetailOutput(
            report_id=detail.report_id,
            report_number=detail.report_number,
            status=detail.status,
            opened_at=detail.opened_at,
            target=AdminReportTargetOutput(
                type=target.type,
                id=target.id,
                name=target.name,
                member_since=target.member_since,
                event_count=target.event_count,
                moderation_status=target.moderation_status,
            ),
            reason=detail.reason,
            description=detail.description,
            reported_by=AdminReportUserOutput(
                id=detail.reported_by.id,
                name=detail.reported_by.name,
            ),
            reported_at=detail.reported_at,
            previous_reports=AdminReportPreviousReportsOutput(
                total=previous.total,
                archived=previous.archived,
                resolved_with_action=previous.resolved_with_action,
            ),
            resolution=AdminReportAssembler._to_resolution_dto(detail.resolution),
        )

    @staticmethod
    def to_dto(detail: AdminReportDetail) -> AdminReportDetailOutput:
        return AdminReportAssembler.to_detail_dto(detail)

    @staticmethod
    def _to_resolution_dto(
        resolution: AdminReportResolution | None,
    ) -> AdminReportResolutionOutput | None:
        if resolution is None:
            return None
        return AdminReportResolutionOutput(
            resolved_by=AdminReportUserOutput(
                id=resolution.resolved_by.id,
                name=resolution.resolved_by.name,
            ),
            resolved_at=resolution.resolved_at,
            action=resolution.action,
        )

