from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BusinessRegistration:
    email: str
    password: str
    business_name: str
    cnpj: str
    address: str
    latitude: float
    longitude: float
    accepted_terms_version: str
    phone: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class BusinessProfile:
    user_id: UUID
    cnpj: str
    address: str
    updated_at: datetime
    business_latitude: float | None = None
    business_longitude: float | None = None
