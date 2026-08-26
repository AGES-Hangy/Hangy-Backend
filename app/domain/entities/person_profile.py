from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID
from typing import Optional

@dataclass
class PersonProfile:
    user_id: UUID
    cpf: str
    name: str
    description: Optional[str] = None
    date_of_birth: date
    country: str
    state: str
    city: str
    updated_at: datetime