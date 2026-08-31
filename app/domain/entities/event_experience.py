from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class EventExperience:
    experience_id: UUID | None
    event_participant_id: UUID
    description: str
    created_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExperienceImage:
    photo_id: UUID | None
    experience_id: UUID
    photo_url: str
    created_at: datetime
    deleted_at: datetime | None = None
