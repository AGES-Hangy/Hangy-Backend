from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PersonProfile:
    user_id: UUID
    cpf: str
    date_of_birth: date
    country: str
    state: str
    city: str
    updated_at: datetime
