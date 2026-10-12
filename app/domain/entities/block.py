from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserBlock:
    blocker_id: UUID
    blocked_id: UUID
    created_at: datetime
