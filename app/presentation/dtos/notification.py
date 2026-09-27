__all__ = ["NotificationItemResponse", "NotificationsPaginatedResponse"]


from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import NotificationTypeEnum


class NotificationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: UUID
    type: NotificationTypeEnum
    read: bool
    created_at: datetime
    payload: dict[str, Any]


class NotificationsPaginatedResponse(BaseModel):
    items: list[NotificationItemResponse]
    next_cursor: str | None
    unread_count: int
