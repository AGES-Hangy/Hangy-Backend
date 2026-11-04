__all__ = ["AdminUserModerationMapper"]

from app.domain.entities import (
    BanUserAction,
    RevertUserModerationAction,
    SuspendUserAction,
    UserModerationAction,
)
from app.presentation.dtos.admin_user_moderation import (
    AdminUserModerationInput,
    BanActionInput,
    SuspendActionInput,
)


class AdminUserModerationMapper:
    @staticmethod
    def to_entity(dto: AdminUserModerationInput) -> UserModerationAction:
        if isinstance(dto, BanActionInput):
            return BanUserAction(report_id=dto.report_id)
        if isinstance(dto, SuspendActionInput):
            return SuspendUserAction(
                duration_days=dto.duration_days, report_id=dto.report_id
            )
        return RevertUserModerationAction()
