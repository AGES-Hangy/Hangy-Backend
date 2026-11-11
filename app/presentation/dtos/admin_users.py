from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import ModerationStatusEnum

__all__ = [
    "AdminModerationActorOutput",
    "AdminModerationEntryOutput",
    "AdminUserDetailOutput",
    "AdminUserMetricsOutput",
    "AdminUserOutput",
    "AdminUsersOutput",
]


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


class AdminUserMetricsOutput(BaseModel):
    event_count: int
    event_cancelled_count: int
    report_count: int
    report_upheld_count: int


class AdminModerationActorOutput(BaseModel):
    id: UUID
    name: str | None


class AdminModerationEntryOutput(BaseModel):
    action: Literal["BANNED", "SUSPENDED", "REVERTED"]
    actor: AdminModerationActorOutput | None
    occurred_at: datetime
    report_id: UUID | None


class AdminUserDetailOutput(BaseModel):
    user_id: UUID
    name: str | None
    email: str
    member_since: date
    moderation_status: ModerationStatusEnum
    banned_at: datetime | None
    suspended_until: datetime | None
    metrics: AdminUserMetricsOutput
    moderation_history: list[AdminModerationEntryOutput]
