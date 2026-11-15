__all__ = ["AdminEventModerationMapper"]

from app.domain.entities import EventModerationAction, RemoveEventAction
from app.presentation.dtos.admin_event_moderation import AdminEventModerationInput


class AdminEventModerationMapper:
    @staticmethod
    def to_entity(dto: AdminEventModerationInput) -> EventModerationAction:
        return RemoveEventAction(report_id=dto.report_id)
