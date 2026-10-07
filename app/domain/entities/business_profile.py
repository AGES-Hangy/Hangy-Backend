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


@dataclass(frozen=True, slots=True)
class OwnBusinessProfile:
    """A business account as shown to its own owner.

    The display name, bio and phone live on the user row, while CNPJ, address
    and coordinates live on the business profile, so this joins both halves.
    """

    user_id: UUID
    cnpj: str
    address: str
    business_name: str | None = None
    description: str | None = None
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None