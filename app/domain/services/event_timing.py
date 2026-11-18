"""When an event counts as over.

No job flips an event to FINISHED when its end time passes: the organizer can
finish it early (`PATCH /events/{id}/finish`), and otherwise it is over once its
`ends_at` is reached. So the stored status alone is not enough: an event is
over once it is FINISHED *or* its `ends_at` has been reached, and responses
report the status that results from both (`effective_event_status`).
"""

from datetime import UTC, datetime

from app.domain.entities import Event
from app.domain.enums import EventStatusEnum

__all__ = ["effective_event_status", "has_event_ended"]


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on read; treat naive datetimes as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def has_event_ended(event: Event, now: datetime | None = None) -> bool:
    if event.event_status is EventStatusEnum.FINISHED:
        return True
    return _as_utc(event.ends_at) <= (now or datetime.now(UTC))


def effective_event_status(
    event_status: EventStatusEnum, ends_at: datetime, now: datetime | None = None
) -> EventStatusEnum:
    """The status clients see: a published event past its end reads as FINISHED.

    Only PUBLISHED is promoted; a cancelled or draft event keeps its status
    even after its end time.
    """
    if event_status is EventStatusEnum.PUBLISHED and _as_utc(ends_at) <= (
        now or datetime.now(UTC)
    ):
        return EventStatusEnum.FINISHED
    return event_status
