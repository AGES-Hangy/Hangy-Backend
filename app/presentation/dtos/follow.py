from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

__all__ = ["FollowedBusinessOutput", "FollowingOutput"]


class FollowedBusinessOutput(BaseModel):
    user_id: UUID
    business_name: str | None
    photo_url: str | None
    city: str | None
    followed_at: datetime


class FollowingOutput(BaseModel):
    items: list[FollowedBusinessOutput]
    next_cursor: str | None