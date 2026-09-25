from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.domain.enums import UserTypeEnum

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
CPF_PATTERN = r"^\d{11}$"
CNPJ_PATTERN = r"^\d{14}$"
# Brazilian numbers only: optional +55/55 country code, a 2-digit DDD (plain
# or parenthesized), then an 8-digit landline or 9-digit mobile number, with
# an optional space/dot/dash between the DDD and the number and between the
# two halves of the number itself. Covers "51999990000", "(51) 99999-0000",
# "51 3333-0000" and "+55 51 99999-0000" alike.
PHONE_PATTERN = r"^(?:\+?55\s?)?\(?[1-9][0-9]\)?[\s.-]?9?[0-9]{4}[\s.-]?[0-9]{4}$"


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
    phone: str | None = Field(default=None, max_length=20, pattern=PHONE_PATTERN)
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
    phone: str | None = Field(default=None, max_length=20, pattern=PHONE_PATTERN)
    description: str | None = Field(default=None, max_length=500)
    location: LocationInput
    address: str = Field(min_length=1, max_length=255)
    accepted_terms_version: str = Field(min_length=1, max_length=50)


RegisterRequest = Annotated[
    RegisterPersonalRequest | RegisterBusinessRequest,
    Field(discriminator="user_type"),
]


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    password: SecretStr


class AuthPersonalUserOutput(BaseModel):
    id: UUID
    email: str
    user_type: Literal[UserTypeEnum.PERSONAL]
    name: str


class AuthBusinessUserOutput(BaseModel):
    id: UUID
    email: str
    user_type: Literal[UserTypeEnum.BUSINESS]
    business_name: str


class AuthOutput(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    user: AuthPersonalUserOutput | AuthBusinessUserOutput


class PersonalProfileOutput(BaseModel):
    date_of_birth: date
    city: str
    state: str
    photo_url: str | None = None


class BusinessProfileOutput(BaseModel):
    cnpj: str
    address: str
    latitude: float | None = None
    longitude: float | None = None
    photo_url: str | None = None


class CurrentUserOutput(BaseModel):
    id: UUID
    email: str
    user_type: UserTypeEnum
    name: str | None = None
    profile: PersonalProfileOutput | BusinessProfileOutput | None = None
