from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "BusinessLocationInput",
    "BusinessLocationOutput",
    "BusinessMeOutput",
    "BusinessProfileUpdateInput",
    "BusinessProfileUpdateOutput",
]


class BusinessLocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float
    longitude: float


class BusinessLocationOutput(BaseModel):
    latitude: float
    longitude: float


class BusinessMeOutput(BaseModel):
    user_id: UUID
    business_name: str | None
    cnpj: str
    description: str | None
    address: str
    location: BusinessLocationOutput | None
    phone: str | None


class BusinessProfileUpdateInput(BaseModel):
    # CNPJ is not editable: ignored if sent in the payload.
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    business_name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    address: str | None = Field(default=None, min_length=1, max_length=255)
    location: BusinessLocationInput | None = None
    cnpj: str | None = None

    @field_validator("business_name", "address")
    @classmethod
    def reject_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class BusinessProfileUpdateOutput(BaseModel):
    user_id: UUID
    business_name: str | None
    description: str | None
    address: str
    location: BusinessLocationOutput | None
    updated_at: datetime
