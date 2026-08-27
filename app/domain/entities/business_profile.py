from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BusinessProfile:
    user_id: UUID
    cnpj: str
    business_name: str
    updated_at: datetime
    description: str | None = None
    business_latitude: float | None = None
    business_longitude: float | None = None
