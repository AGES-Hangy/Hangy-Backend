from app.domain.entities import (
    AdminReportDetail,
    AdminReportOrganizer,
    AdminReportQueueItem,
    AdminReportResolution,
    AdminReportsPage,
    ReportTargetType,
)
from app.domain.enums import UserTypeEnum
from app.presentation.dtos.admin_report import (
    AdminReportDetailOutput,
    AdminReportItemOutput,
    AdminReportOrganizerOutput,
    AdminReportPreviousReportsOutput,
    AdminReportResolutionOutput,
    AdminReportsOutput,
    AdminReportTargetOutput,
    AdminReportUserOutput,
)

__all__ = ["AdminReportAssembler"]

EXCERPT_LENGTH = 100
TARGET_TYPE_BY_USER_TYPE: dict[UserTypeEnum, ReportTargetType] = {
    UserTypeEnum.PERSONAL: "USER",
    UserTypeEnum.BUSINESS: "BUSINESS",
}


class AdminReportAssembler:
    @staticmethod
    def to_detail_dto(detail: AdminReportDetail) -> AdminReportDetailOutput:
        target = detail.target
        previous = detail.previous_reports
        # `organizer` is left unset (and so omitted, see the route's
        # response_model_exclude_unset) unless the target is an event.
        extra = {}
        if detail.organizer is not None:
            extra["organizer"] = AdminReportAssembler._to_organizer_dto(
                detail.organizer
            )
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
            **extra,
        )

    @staticmethod
    def to_dto(detail: AdminReportDetail) -> AdminReportDetailOutput:
        return AdminReportAssembler.to_detail_dto(detail)

    @staticmethod
    def to_queue_dto(page: AdminReportsPage) -> AdminReportsOutput:
        return AdminReportsOutput(
            items=[
                AdminReportAssembler._to_queue_item_dto(item) for item in page.items
            ],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_queue_item_dto(item: AdminReportQueueItem) -> AdminReportItemOutput:
        target_type: ReportTargetType | None = None
        target_name = None
        if item.reported_user_type is not None:
            target_type = TARGET_TYPE_BY_USER_TYPE[item.reported_user_type]
            target_name = item.reported_user_name
        elif item.reported_event_title is not None:
            target_type = "EVENT"
            target_name = item.reported_event_title

        excerpt = item.description
        if len(excerpt) > EXCERPT_LENGTH:
            excerpt = excerpt[:EXCERPT_LENGTH].rstrip() + "..."

        return AdminReportItemOutput(
            report_id=item.report_id,
            report_number=item.report_number,
            target_type=target_type,
            target_name=target_name,
            report_count=item.report_count,
            status=item.status,
            reason=item.report_type,
            description_excerpt=excerpt,
            opened_at=item.opened_at,
        )

    @staticmethod
    def _to_organizer_dto(
        organizer: AdminReportOrganizer,
    ) -> AdminReportOrganizerOutput:
        return AdminReportOrganizerOutput(
            user_id=organizer.user_id,
            name=organizer.name,
            photo_url=organizer.photo_url,
            moderation_status=organizer.moderation_status,
            events_count=organizer.events_count,
            reports_count=organizer.reports_count,
        )

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
