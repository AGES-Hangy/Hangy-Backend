from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.domain.entities.event import Event
    from app.domain.entities.event_participant import EventParticipant

__all__ = [
    "EventExperience",
    "EventExperienceAccess",
    "ExperienceImage",
    "NewEventExperience",
]


@dataclass(frozen=True, slots=True)
class NewEventExperience:
    description: str


@dataclass(frozen=True, slots=True)
class EventExperience:
    experience_id: UUID | None
    event_participant_id: UUID
    description: str
    created_at: datetime
    deleted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventExperienceAccess:
    event: Event
    participant: EventParticipant | None
    organizer_blocked_viewer: bool


@dataclass(frozen=True, slots=True)
class ExperienceImage:
    photo_id: UUID | None
    experience_id: UUID
    photo_url: str
    created_at: datetime
    deleted_at: datetime | None = None
