from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.domain.enums import UserRoleEnum, UserTypeEnum

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
CPF_PATTERN = r"^\d{11}$"
CNPJ_PATTERN = r"^\d{14}$"


class LocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float


class RegisterPersonalRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    user_type: Literal[UserTypeEnum.PERSONAL] = UserTypeEnum.PERSONAL
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    password: SecretStr = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    cpf: str = Field(pattern=CPF_PATTERN)
    phone: str | None = Field(default=None, max_length=20)
    date_of_birth: date
    country: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    accepted_terms_version: str = Field(min_length=1, max_length=50)


class RegisterBusinessRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    user_type: Literal[UserTypeEnum.BUSINESS] = UserTypeEnum.BUSINESS
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    password: SecretStr = Field(min_length=8, max_length=128)
    business_name: str = Field(min_length=1, max_length=120)
    cnpj: str = Field(pattern=CNPJ_PATTERN)
    phone: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=500)
    location: LocationInput
    address: str = Field(min_length=1, max_length=255)
    accepted_terms_version: str = Field(min_length=1, max_length=50)


RegisterRequest = Annotated[
    RegisterPersonalRequest | RegisterBusinessRequest,
    Field(discriminator="user_type"),
]


class RegisterPersonalUserOutput(BaseModel):
    id: UUID
    email: str
    user_type: Literal[UserTypeEnum.PERSONAL]
    name: str


class RegisterBusinessUserOutput(BaseModel):
    id: UUID
    email: str
    user_type: Literal[UserTypeEnum.BUSINESS]
    business_name: str


class RegisterOutput(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    user: RegisterPersonalUserOutput | RegisterBusinessUserOutput


class UserOutput(BaseModel):
    user_id: UUID
    email: str
    user_type: UserTypeEnum
    role: UserRoleEnum
    created_at: datetime


class TokenOutput(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
