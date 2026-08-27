from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import UserRoleEnum, UserTypeEnum


@dataclass(frozen=True, slots=True)
class UserCredentials:
    email: str
    password: str
    user_type: UserTypeEnum = UserTypeEnum.PERSONAL


@dataclass(frozen=True, slots=True)
class User:
    user_id: UUID | None
    user_type: UserTypeEnum
    email: str
    password_hash: str
    created_at: datetime
    updated_at: datetime
    role: UserRoleEnum = UserRoleEnum.USER
    user_phone: str | None = None
    profile_photo_url: str | None = None
    deleted_at: datetime | None = None
