__all__ = [
    "AdminUserModerationInput",
    "AdminUserModerationOutput",
    "BanActionInput",
    "RevertActionInput",
    "SuspendActionInput",
]

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import ModerationStatusEnum, UserRoleEnum

# A suspension longer than a year has no real precedent in the product; past
# that an admin should ban instead.
MAX_SUSPENSION_DURATION_DAYS = 365


class BanActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["BAN"]
    report_id: UUID | None = None


class SuspendActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["SUSPEND"]
    duration_days: int = Field(gt=0, le=MAX_SUSPENSION_DURATION_DAYS)
    report_id: UUID | None = None


class RevertActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["REVERT"]


AdminUserModerationInput = Annotated[
    BanActionInput | SuspendActionInput | RevertActionInput,
    Field(discriminator="action"),
]


class AdminUserModerationOutput(BaseModel):
    """The moderated user's record, same shape task 248 (user detail) returns."""

    user_id: UUID
    name: str | None
    email: str
    role: UserRoleEnum
    moderation_status: ModerationStatusEnum
    suspended_until: datetime | None
    created_at: datetime
