from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import ModerationStatusEnum


class AdminUserOutput(BaseModel):
    user_id: UUID
    name: str | None
    moderation_status: ModerationStatusEnum
    suspended_until: datetime | None
    event_count: int
    report_count: int


class AdminUsersOutput(BaseModel):
    items: list[AdminUserOutput]
    next_cursor: str | None
