__all__ = ["AdminEventModerationAssembler"]

from app.domain.entities import EventModerationResult
from app.presentation.dtos.admin_event_moderation import AdminEventModerationOutput


class AdminEventModerationAssembler:
    @staticmethod
    def to_dto(result: EventModerationResult) -> AdminEventModerationOutput:
        return AdminEventModerationOutput(
            event_id=result.event_id,
            moderation_status=result.moderation_status,
            removed_at=result.removed_at,
            report_id=result.report_id,
            report_status=result.report_status,
        )
