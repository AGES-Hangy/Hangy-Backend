from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.tag import Tag
from app.domain.enums import UserConnectionStatusEnum, UserTypeEnum


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
    is_blocked: bool
    connections_count: int


__all__ = ["UserProfileData"]
