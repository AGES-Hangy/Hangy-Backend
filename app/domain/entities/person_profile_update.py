from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

__all__ = ["EditedPersonProfile", "PersonProfileUpdate", "Unset"]


class Unset(Enum):
    """Marks a field the PATCH payload left out, as opposed to one sent as null."""

    UNSET = "UNSET"


@dataclass(frozen=True, slots=True)
class PersonProfileUpdate:
    """The editable fields of a personal profile; UNSET ones stay unchanged."""

    name: str | Unset = Unset.UNSET
    description: str | None | Unset = Unset.UNSET
    state: str | Unset = Unset.UNSET
    city: str | Unset = Unset.UNSET


@dataclass(frozen=True, slots=True)
class EditedPersonProfile:
    user_id: UUID
    name: str | None
    description: str | None
    state: str
    city: str
    updated_at: datetime
