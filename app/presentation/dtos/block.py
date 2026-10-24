from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class BlockedUserOutput(BaseModel):
    user_id: UUID
    name: str | None
    photo_url: str | None
    blocked_at: datetime


class BlockedUsersOutput(BaseModel):
    items: list[BlockedUserOutput]
    next_cursor: str | None
