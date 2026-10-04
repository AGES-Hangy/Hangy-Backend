from uuid import UUID

from pydantic import BaseModel

__all__ = [
    "ProfileTagOutput",
    "UserProfileCountsOutput",
    "UserProfileDataOutput",
    "UserProfileOutput",
]


class ProfileTagOutput(BaseModel):
    id: UUID
    name: str


class UserProfileDataOutput(BaseModel):
    id: UUID
    name: str | None
    description: str | None
    photo_url: str | None
    tags: list[ProfileTagOutput]
    connections_count: int


class UserProfileCountsOutput(BaseModel):
    past: int
    confirmed: int
    photos: int


class UserProfileOutput(BaseModel):
    profile: UserProfileDataOutput
    counts: UserProfileCountsOutput
