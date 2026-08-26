from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from typing import Optional, Tuple
from app.domain.enums import EventStatusEnum, EventPrivacyEnum

@dataclass
class Event:
    event_id: UUID
    event_creator_id: UUID
    event_title: str
    event_description: Optional[str] = None
    location: Tuple[float, float]
    starts_at: datetime
    ends_at: datetime
    max_participants: Optional[int] = None
    event_status: EventStatusEnum
    event_privacy: EventPrivacyEnum
    cover_photo_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None