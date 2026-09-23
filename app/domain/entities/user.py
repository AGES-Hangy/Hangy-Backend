from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.domain.enums import UserRoleEnum, UserTypeEnum


@dataclass(frozen=True, slots=True)
class PersonRegistration:
    email: str
    password: str
    name: str
    cpf: str
    date_of_birth: date
    country: str
    state: str
    city: str
    accepted_terms_version: str
    phone: str | None = None


@dataclass(frozen=True, slots=True)
class User:
    user_id: UUID | None
    user_type: UserTypeEnum
    email: str
    password_hash: str
    created_at: datetime
    updated_at: datetime
    role: UserRoleEnum = UserRoleEnum.USER
    name: str | None = None
    description: str | None = None
    user_phone: str | None = None
    profile_photo_url: str | None = None
    accepted_terms_at: datetime | None = None
    accepted_terms_version: str | None = None
    deleted_at: datetime | None = None
