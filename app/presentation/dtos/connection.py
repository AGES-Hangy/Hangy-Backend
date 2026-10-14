from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.domain.enums import UserConnectionStatusEnum


class SendConnectionRequestInput(BaseModel):
    receiver_id: UUID


class SendConnectionRequestOutput(BaseModel):
    connection_id: UUID
    requester_id: UUID
    receiver_id: UUID
    status: UserConnectionStatusEnum
    created_at: datetime


class PendingConnectionUserOutput(BaseModel):
    id: UUID
    name: str | None
    photo_url: str | None


class PendingConnectionOutput(BaseModel):
    connection_id: UUID
    user: PendingConnectionUserOutput
    created_at: datetime


class PendingConnectionsOutput(BaseModel):
    items: list[PendingConnectionOutput]
    next_cursor: str | None
