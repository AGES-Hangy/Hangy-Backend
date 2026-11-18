from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr

from app.domain.enums import UserRoleEnum, UserTypeEnum

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# Emails are stored and compared lower-cased: mobile keyboards capitalize the
# first letter, and "Ana@x.com" and "ana@x.com" are the same mailbox.
EmailInput = Annotated[
    str,
    Field(max_length=254, pattern=EMAIL_PATTERN),
    AfterValidator(str.lower),
]
# Upper bound for any password the API hashes or verifies, so a huge body can't
# make a single request spend seconds in the hasher.
PASSWORD_MAX_LENGTH = 128
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
    email: EmailInput
    password: SecretStr = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    cpf: str = Field(pattern=CPF_PATTERN)
    phone: str | None = Field(default=None, max_length=20, pattern=PHONE_PATTERN)
    date_of_birth: date
    state: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    accepted_terms_version: str = Field(min_length=1, max_length=50)


class RegisterBusinessRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    user_type: Literal[UserTypeEnum.BUSINESS] = UserTypeEnum.BUSINESS
    email: EmailInput
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

    email: EmailInput
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class AuthPersonalUserOutput(BaseModel):
    id: UUID
    email: str
    user_type: Literal[UserTypeEnum.PERSONAL]
    role: UserRoleEnum
    name: str


class AuthBusinessUserOutput(BaseModel):
    id: UUID
    email: str
    user_type: Literal[UserTypeEnum.BUSINESS]
    role: UserRoleEnum
    business_name: str


class AuthOutput(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int = Field(description="Segundos ate o access_token expirar.")
    refresh_token: str = Field(
        description=(
            "Token opaco para POST /auth/refresh. Vale uma unica vez: cada "
            "refresh devolve um novo."
        )
    )
    refresh_expires_in: int = Field(description="Segundos ate o refresh_token expirar.")
    user: AuthPersonalUserOutput | AuthBusinessUserOutput


class RefreshTokenInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    refresh_token: str = Field(min_length=1, max_length=256)


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
    role: UserRoleEnum
    name: str | None = None
    profile: PersonalProfileOutput | BusinessProfileOutput | None = None


class DeleteAccountInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
