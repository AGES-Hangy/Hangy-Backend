from collections.abc import Collection
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, NewEvent
from app.domain.enums import EventStatusEnum

MAX_EVENT_TAGS = 5
MIN_LATITUDE, MAX_LATITUDE = -90.0, 90.0
MIN_LONGITUDE, MAX_LONGITUDE = -180.0, 180.0


class EventRepository(Protocol):
    def add(self, event: NewEvent) -> Event: ...

    def find_existing_tag_ids(self, tag_ids: Collection[UUID]) -> set[UUID]: ...
    def get_by_id(self, event_id: UUID) -> Event | None: ...
    def cancel(self, event_id: UUID) -> Event: ...


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


class EventAlreadyFinishedError(Exception):
    """Raised when an event that has already finished is changed."""


class EventNotFoundError(Exception):
    """Raised when the requested event does not exist or is not visible."""


class NotEventOrganizerError(Exception):
    """Raised when someone other than the creator changes an event."""


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

    def cancel(self, event_id: UUID, requester_id: UUID) -> Event:
        event = self.repository.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError
        if event.event_creator_id != requester_id:
            raise NotEventOrganizerError
        if event.event_status is EventStatusEnum.FINISHED:
            raise EventAlreadyFinishedError
        return self.repository.cancel(event_id)
