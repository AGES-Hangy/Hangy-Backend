from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

__all__ = [
    "BusinessFollowerOutput",
    "BusinessFollowerTagOutput",
    "BusinessFollowersOutput",
    "FollowedBusinessOutput",
    "FollowingOutput",
]


class FollowedBusinessOutput(BaseModel):
    user_id: UUID
    business_name: str | None
    photo_url: str | None
    city: str | None
    followed_at: datetime


class FollowingOutput(BaseModel):
    items: list[FollowedBusinessOutput]
    next_cursor: str | None


class BusinessFollowerTagOutput(BaseModel):
    id: UUID
    name: str


class BusinessFollowerOutput(BaseModel):
    user_id: UUID
    name: str
    photo_url: str | None
    tags: list[BusinessFollowerTagOutput]


class BusinessFollowersOutput(BaseModel):
    items: list[BusinessFollowerOutput]
    total: int
    next_cursor: str | None
