from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "ProfileTagOutput",
    "UserProfileCountsOutput",
    "UserProfileDataOutput",
    "UserProfileOutput",
    "UserProfileUpdateInput",
    "UserProfileUpdateOutput",
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


class UserProfileUpdateInput(BaseModel):
    # CPF, email and date of birth are not editable: like any other unknown
    # field they are ignored instead of rejected, and never applied.
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    # The length limit is a business rule answered with 400, so the service
    # checks it against PROFILE_DESCRIPTION_MAX_LENGTH instead of Pydantic.
    description: str | None = None
    state: str | None = Field(default=None, min_length=1, max_length=100)
    city: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("name", "state", "city")
    @classmethod
    def reject_null(cls, value: str | None) -> str:
        # Only the bio can be cleared; these columns are required.
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class UserProfileUpdateOutput(BaseModel):
    id: UUID
    name: str | None
    description: str | None
    city: str
    updated_at: datetime
