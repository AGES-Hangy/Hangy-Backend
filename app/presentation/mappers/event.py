from datetime import UTC, datetime
from uuid import UUID

from app.domain.entities import NewEvent
from app.presentation.dtos import CreateEventInput


class EventMapper:
    @staticmethod
    def to_new_event(dto: CreateEventInput, creator_id: UUID) -> NewEvent:
        return NewEvent(
            event_creator_id=creator_id,
            event_title=dto.title,
            event_latitude=dto.location.latitude,
            event_longitude=dto.location.longitude,
            starts_at=EventMapper._as_utc(dto.event_date),
            ends_at=EventMapper._as_utc(dto.end_date),
            event_privacy=dto.privacy,
            event_description=dto.description,
            location_name=dto.location_name,
            max_participants=dto.max_participants,
            cover_photo_url=dto.cover_photo_url,
            # dict.fromkeys drops duplicates without losing the client's order.
            tag_ids=tuple(dict.fromkeys(dto.tag_ids)),
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """Clients may omit the offset; the domain always compares in UTC."""
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
