from datetime import UTC, datetime
from uuid import UUID

from app.domain.entities import EventUpdate, NewEvent
from app.presentation.dtos import CreateEventInput, UpdateEventInput


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
    def to_event_update(dto: UpdateEventInput) -> EventUpdate:
        return EventUpdate(
            event_title=dto.title,
            event_description=dto.description,
            event_latitude=(
                dto.location.latitude if dto.location is not None else None
            ),
            event_longitude=(
                dto.location.longitude if dto.location is not None else None
            ),
            location_name=dto.location_name,
            starts_at=(
                EventMapper._as_utc(dto.event_date)
                if dto.event_date is not None
                else None
            ),
            ends_at=(
                EventMapper._as_utc(dto.end_date) if dto.end_date is not None else None
            ),
            cover_photo_url=dto.cover_photo_url,
            tag_ids=(
                tuple(dict.fromkeys(dto.tag_ids)) if dto.tag_ids is not None else ()
            ),
            fields_to_update=frozenset(dto.model_fields_set),
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """Clients may omit the offset; the domain always compares in UTC."""
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
