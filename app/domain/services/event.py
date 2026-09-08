from collections.abc import Collection
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, EventUpdate, NewEvent
from app.domain.enums import EventStatusEnum

MAX_EVENT_TAGS = 5
MIN_LATITUDE, MAX_LATITUDE = -90.0, 90.0
MIN_LONGITUDE, MAX_LONGITUDE = -180.0, 180.0


class EventRepository(Protocol):
    def add(self, event: NewEvent) -> Event: ...

    def find_existing_tag_ids(self, tag_ids: Collection[UUID]) -> set[UUID]: ...

    def get(self, event_id: UUID) -> Event | None: ...

    def update(self, event: Event, tag_ids: Collection[UUID] | None) -> Event: ...


class EventStartsInThePastError(Exception):
    """Raised when an event is published with a start date that already passed."""


class EventEndsBeforeItStartsError(Exception):
    """Raised when the end date of an event is not after its start date."""


class InvalidEventCoordinatesError(Exception):
    """Raised when the event coordinates fall outside the valid ranges."""


class TooManyEventTagsError(Exception):
    """Raised when an event carries more tags than the domain allows."""


class EventTagNotFoundError(Exception):
    """Raised when an event references a tag that does not exist."""


class EventNotFoundError(Exception):
    """Raised when an event does not exist or is no longer visible."""


class EventNotOrganizerError(Exception):
    """Raised when someone other than the organizer tries to edit an event."""


class EventAlreadyFinishedError(Exception):
    """Raised when an event that has finished is edited."""


class EventsService:
    def __init__(self, repository: EventRepository) -> None:
        self.repository = repository

    def create(self, event: NewEvent) -> Event:
        """Validate and publish an event, with its organizer already resolved."""
        if event.starts_at <= datetime.now(UTC):
            raise EventStartsInThePastError
        if event.ends_at <= event.starts_at:
            raise EventEndsBeforeItStartsError
        if not (
            MIN_LATITUDE <= event.event_latitude <= MAX_LATITUDE
            and MIN_LONGITUDE <= event.event_longitude <= MAX_LONGITUDE
        ):
            raise InvalidEventCoordinatesError
        if len(event.tag_ids) > MAX_EVENT_TAGS:
            raise TooManyEventTagsError

        # Checking every tag before writing keeps a bad tag from persisting an event.
        if event.tag_ids:
            existing = self.repository.find_existing_tag_ids(event.tag_ids)
            if len(existing) != len(event.tag_ids):
                raise EventTagNotFoundError

        return self.repository.add(event)

    def update(self, event_id: UUID, organizer_id: UUID, changes: EventUpdate) -> Event:
        """Apply a partial update after enforcing the event editing rules."""
        event = self.repository.get(event_id)
        if event is None:
            raise EventNotFoundError
        if event.event_creator_id != organizer_id:
            raise EventNotOrganizerError
        if event.event_status is EventStatusEnum.FINISHED:
            raise EventAlreadyFinishedError

        starts_at = (
            changes.starts_at
            if "event_date" in changes.fields_to_update
            else event.starts_at
        )
        ends_at = (
            changes.ends_at if "end_date" in changes.fields_to_update else event.ends_at
        )
        if "event_date" in changes.fields_to_update and starts_at <= datetime.now(UTC):
            raise EventStartsInThePastError
        if ends_at <= starts_at:
            raise EventEndsBeforeItStartsError
        if "location" in changes.fields_to_update and not (
            MIN_LATITUDE <= changes.event_latitude <= MAX_LATITUDE
            and MIN_LONGITUDE <= changes.event_longitude <= MAX_LONGITUDE
        ):
            raise InvalidEventCoordinatesError

        tag_ids: Collection[UUID] | None = None
        if "tag_ids" in changes.fields_to_update:
            tag_ids = changes.tag_ids
            if len(tag_ids) > MAX_EVENT_TAGS:
                raise TooManyEventTagsError
            if tag_ids:
                existing = self.repository.find_existing_tag_ids(tag_ids)
                if len(existing) != len(tag_ids):
                    raise EventTagNotFoundError

        updated_event = Event(
            event_id=event.event_id,
            event_creator_id=event.event_creator_id,
            event_title=(
                changes.event_title
                if "title" in changes.fields_to_update
                else event.event_title
            ),
            event_latitude=(
                changes.event_latitude
                if "location" in changes.fields_to_update
                else event.event_latitude
            ),
            event_longitude=(
                changes.event_longitude
                if "location" in changes.fields_to_update
                else event.event_longitude
            ),
            starts_at=starts_at,
            ends_at=ends_at,
            event_status=event.event_status,
            event_privacy=event.event_privacy,
            created_at=event.created_at,
            updated_at=event.updated_at,
            event_description=(
                changes.event_description
                if "description" in changes.fields_to_update
                else event.event_description
            ),
            location_name=(
                changes.location_name
                if "location_name" in changes.fields_to_update
                else event.location_name
            ),
            max_participants=event.max_participants,
            cover_photo_url=(
                changes.cover_photo_url
                if "cover_photo_url" in changes.fields_to_update
                else event.cover_photo_url
            ),
            deleted_at=event.deleted_at,
        )
        return self.repository.update(updated_event, tag_ids)
