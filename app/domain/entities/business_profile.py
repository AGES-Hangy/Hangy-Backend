from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BusinessProfile:
    user_id: UUID
    cnpj: str
    updated_at: datetime
    business_latitude: float | None = None
    business_longitude: float | None = None
