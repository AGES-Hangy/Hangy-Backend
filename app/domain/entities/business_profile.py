from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.entities.person_profile_update import Unset

__all__ = [
    "BusinessProfile",
    "BusinessProfileLocation",
    "BusinessProfileUpdate",
    "BusinessRegistration",
    "EditedBusinessProfile",
    "OwnBusinessProfile",
]


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
class BusinessProfileLocation:
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class BusinessProfileUpdate:
    business_name: str | Unset = Unset.UNSET
    description: str | None | Unset = Unset.UNSET
    address: str | Unset = Unset.UNSET
    location: BusinessProfileLocation | None | Unset = Unset.UNSET


@dataclass(frozen=True, slots=True)
class EditedBusinessProfile:
    user_id: UUID
    business_name: str | None
    description: str | None
    address: str
    latitude: float | None
    longitude: float | None
    updated_at: datetime


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
