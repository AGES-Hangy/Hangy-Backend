from dataclasses import dataclass
from uuid import UUID
from datetime import datetime
from typing import Optional, Tuple

@dataclass
class BusinessProfile:
    user_id: UUID
    cnpj: str
    business_name: str
    description: Optional[str] = None
    location: Optional[Tuple[float, float]] = None
    updated_at: datetime