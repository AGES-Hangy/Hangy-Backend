from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    AdminEventDetail,
    AdminEventDetailRecord,
    AdminEventOrganizer,
)
from app.domain.services.admin_users import derive_moderation_status


class AdminEventsRepository(Protocol):
    def get_detail(self, event_id: UUID) -> AdminEventDetailRecord | None: ...


class AdminEventNotFoundError(Exception):
    """Raised when event_id matches no event."""


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; treat naive datetimes as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AdminEventsService:
    def __init__(self, repository: AdminEventsRepository) -> None:
        self.repository = repository

    def get_event_detail(
        self, event_id: UUID, now: datetime | None = None
    ) -> AdminEventDetail:
        now = now or datetime.now(UTC)
        record = self.repository.get_detail(event_id)
        if record is None:
            raise AdminEventNotFoundError

        organizer = record.organizer
        return AdminEventDetail(
            event_id=record.event_id,
            title=record.title,
            description=record.description,
            starts_at=_as_utc(record.starts_at),
            ends_at=_as_utc(record.ends_at),
            location_name=record.location_name,
            location_neighborhood=record.location_neighborhood,
            location_city=record.location_city,
            latitude=record.latitude,
            longitude=record.longitude,
            privacy=record.privacy,
            status=record.status,
            moderation_status=record.moderation_status,
            removed_at=_as_utc(record.removed_at) if record.removed_at else None,
            cover_photo_url=record.cover_photo_url,
            max_participants=record.max_participants,
            created_at=_as_utc(record.created_at),
            tags=record.tags,
            organizer=AdminEventOrganizer(
                user_id=organizer.user_id,
                name=organizer.name,
                photo_url=organizer.photo_url,
                moderation_status=derive_moderation_status(
                    organizer.banned_at, organizer.suspended_until, now
                ),
                event_count=organizer.event_count,
                report_count=organizer.report_count,
            ),
            metrics=record.metrics,
        )


__all__ = [
    "AdminEventNotFoundError",
    "AdminEventsRepository",
    "AdminEventsService",
]
