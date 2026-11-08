__all__ = ["AdminUserModerationAssembler"]

from datetime import UTC, datetime

from app.domain.entities import User
from app.domain.enums import ModerationStatusEnum
from app.domain.services.admin_users import derive_moderation_status
from app.presentation.dtos.admin_user_moderation import AdminUserModerationOutput


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; treat naive datetimes as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AdminUserModerationAssembler:
    @staticmethod
    def to_dto(user: User, now: datetime) -> AdminUserModerationOutput:
        if user.user_id is None:
            raise ValueError("A moderated user must have an id")
        moderation_status = derive_moderation_status(
            user.banned_at, user.suspended_until, now
        )
        return AdminUserModerationOutput(
            user_id=user.user_id,
            name=user.name,
            email=user.email,
            role=user.role,
            moderation_status=moderation_status,
            # Only a running suspension has an end date worth showing.
            suspended_until=(
                _as_utc(user.suspended_until)
                if moderation_status == ModerationStatusEnum.SUSPENDED
                and user.suspended_until
                else None
            ),
            created_at=user.created_at,
        )
