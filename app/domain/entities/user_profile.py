from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.tag import Tag
from app.domain.enums import UserConnectionStatusEnum, UserTypeEnum

__all__ = ["UserProfile", "UserProfileCounts", "UserProfileData"]


@dataclass(frozen=True, slots=True)
class UserProfileCounts:
    past: int
    confirmed: int
    photos: int
    connections: int


@dataclass(frozen=True, slots=True)
class UserProfile:
    user_id: UUID
    name: str | None
    description: str | None
    photo_url: str | None
    tags: tuple[Tag, ...]
    counts: UserProfileCounts


@dataclass(frozen=True, slots=True)
class UserProfileData:
    user_id: UUID
    user_type: UserTypeEnum
    name: str | None
    description: str | None
    photo_url: str | None
    tags: tuple[Tag, ...]
    connection_status: UserConnectionStatusEnum | None
    is_following: bool
    connections_count: int
