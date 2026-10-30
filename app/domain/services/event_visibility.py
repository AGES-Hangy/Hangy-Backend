from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domain.entities.event import Event, EventVisibilityView
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)
from app.domain.services.event_location import resolve_location


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def has_full_event_access(
    event: Event,
    viewer_id: UUID,
    participation_status: EventParticipantStatusEnum | None,
) -> bool:
    """Whether the viewer may see the full event details instead of a preview.

    PUBLIC events are always full. PRIVATE and INVITE_ONLY events grant full
    access only to their organizer and CONFIRMED participants.
    """
    return (
        event.event_privacy is EventPrivacyEnum.PUBLIC
        or event.event_creator_id == viewer_id
        or participation_status is EventParticipantStatusEnum.CONFIRMED
    )


def is_event_preview_for_viewer(
    event: Event,
    viewer_id: UUID,
    participation_status: EventParticipantStatusEnum | None,
) -> bool:
    """Whether a listing must mask the event's details as a preview."""
    return (
        event.event_privacy is EventPrivacyEnum.PRIVATE
        and not has_full_event_access(event, viewer_id, participation_status)
    )


def is_event_visible_to_viewer(
    event: Event,
    viewer_id: UUID,
    participation_status: EventParticipantStatusEnum | None,
    *,
    is_blocked: bool = False,
    reference_time: datetime | None = None,
) -> bool:
    """Single domain rule for whether an event appears in search, feed, or nearby.

    - Deleted, non-PUBLISHED, or past events never appear.
    - Events from an organizer who blocked (or was blocked by) the viewer never appear.
    - PUBLIC and PRIVATE events appear (PRIVATE in preview if not approved).
    - INVITE_ONLY events appear only for the organizer or CONFIRMED participants.
    """
    if is_blocked:
        return False
    if event.deleted_at is not None:
        return False
    if event.event_status is not EventStatusEnum.PUBLISHED:
        return False
    if reference_time is not None and _as_utc(event.starts_at) <= _as_utc(
        reference_time
    ):
        return False
    if event.event_privacy is EventPrivacyEnum.INVITE_ONLY:
        return (
            event.event_creator_id == viewer_id
            or participation_status is EventParticipantStatusEnum.CONFIRMED
        )
    return event.event_privacy in (
        EventPrivacyEnum.PUBLIC,
        EventPrivacyEnum.PRIVATE,
    )


def resolve_event_visibility(
    event: Event,
    viewer_id: UUID,
    participation_status: EventParticipantStatusEnum | None,
    participants_count: int,
) -> EventVisibilityView:
    """Resolve preview state, location, description, and participant count."""
    is_organizer = event.event_creator_id == viewer_id
    is_preview = is_event_preview_for_viewer(event, viewer_id, participation_status)
    location = resolve_location(
        event,
        is_organizer=is_organizer,
        participation_status=participation_status,
    )
    return EventVisibilityView(
        is_preview=is_preview,
        location=location,
        description=None if is_preview else event.event_description,
        participants_count=None if is_preview else participants_count,
    )


def visible_events_query(
    user_id: UUID,
    reference_time: datetime | None = None,
) -> Any:
    """Build the shared SQLAlchemy Select of events visible to `user_id`."""
    from app.infrastructure.repository.search import build_visible_events_query

    return build_visible_events_query(user_id, reference_time=reference_time)


__all__ = [
    "has_full_event_access",
    "is_event_preview_for_viewer",
    "is_event_visible_to_viewer",
    "resolve_event_visibility",
    "visible_events_query",
]
