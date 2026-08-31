from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.domain.enums import UserRoleEnum, UserTypeEnum

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    password: SecretStr = Field(min_length=8, max_length=128)
    user_type: UserTypeEnum = UserTypeEnum.PERSONAL


class UserOutput(BaseModel):
    user_id: UUID
    email: str
    user_type: UserTypeEnum
    role: UserRoleEnum
    created_at: datetime


class TokenOutput(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
