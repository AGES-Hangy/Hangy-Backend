from uuid import UUID

from pydantic import BaseModel


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
