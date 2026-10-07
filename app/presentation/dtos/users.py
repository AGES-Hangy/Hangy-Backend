from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.enums import UserConnectionStatusEnum, UserTypeEnum


class UserProfileTagDTO(BaseModel):
    id: UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class UserProfileDTO(BaseModel):
    id: UUID
    user_type: UserTypeEnum
    name: str | None
    description: str | None
    photo_url: str | None
    tags: list[UserProfileTagDTO]
    connection_status: UserConnectionStatusEnum | None
    is_following: bool
    is_blocked: bool
    connections_count: int

    model_config = ConfigDict(from_attributes=True)


__all__ = ["UserProfileDTO", "UserProfileTagDTO"]
