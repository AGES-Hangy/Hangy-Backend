from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import EventStatusEnum


class CancelEventInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class CancelEventOutput(BaseModel):
    event_id: UUID
    status: EventStatusEnum
    updated_at: datetime
