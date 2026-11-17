"""When an event counts as over.

Nothing flips an event to FINISHED when its end time passes, so the status
alone is not enough: an event is over once it is FINISHED *or* its `ends_at`
has been reached.
"""

from datetime import UTC, datetime

from app.domain.entities import Event
from app.domain.enums import EventStatusEnum

__all__ = ["has_event_ended"]


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on read; treat naive datetimes as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def has_event_ended(event: Event, now: datetime | None = None) -> bool:
    if event.event_status is EventStatusEnum.FINISHED:
        return True
    return _as_utc(event.ends_at) <= (now or datetime.now(UTC))
