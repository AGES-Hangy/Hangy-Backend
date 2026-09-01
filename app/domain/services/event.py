from typing import Protocol
from uuid import UUID

from app.domain.entities import Event
from app.domain.enums import EventStatusEnum


class EventRepository(Protocol):
    def get_by_id(self, event_id: UUID) -> Event | None: ...

    def cancel(self, event_id: UUID) -> Event: ...


class EventAlreadyFinishedError(Exception):
    """Raised when an event that has already finished is changed."""


class EventNotFoundError(Exception):
    """Raised when the requested event does not exist or is not visible."""


class NotEventOrganizerError(Exception):
    """Raised when someone other than the creator changes an event."""


class EventsService:
    def __init__(self, repository: EventRepository) -> None:
        self.repository = repository

    def cancel(self, event_id: UUID, requester_id: UUID) -> Event:
        event = self.repository.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError
        if event.event_creator_id != requester_id:
            raise NotEventOrganizerError
        if event.event_status is EventStatusEnum.FINISHED:
            raise EventAlreadyFinishedError
        return self.repository.cancel(event_id)
