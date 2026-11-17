__all__ = [
    "AdminEventModerationInput",
    "AdminEventModerationOutput",
]

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import EventModerationStatusEnum, ReportStatusEnum


class AdminEventModerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["REMOVE"]
    report_id: UUID | None = None


class AdminEventModerationOutput(BaseModel):
    event_id: UUID
    moderation_status: EventModerationStatusEnum
    removed_at: datetime
    # Null when the removal was not started from a report.
    report_id: UUID | None
    report_status: ReportStatusEnum | None
