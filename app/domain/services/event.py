from collections.abc import Collection
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, EventParticipant, NewEvent
from app.domain.enums import EventParticipantStatusEnum, NotificationTypeEnum

MAX_EVENT_TAGS = 5
MIN_LATITUDE, MAX_LATITUDE = -90.0, 90.0
MIN_LONGITUDE, MAX_LONGITUDE = -180.0, 180.0

VALID_TRANSITIONS: dict[EventParticipantStatusEnum, set[EventParticipantStatusEnum]] = {
    EventParticipantStatusEnum.PENDING: {
        EventParticipantStatusEnum.CONFIRMED,
        EventParticipantStatusEnum.REJECTED,
    },
    EventParticipantStatusEnum.INVITED: {
        EventParticipantStatusEnum.CONFIRMED,
        EventParticipantStatusEnum.REJECTED,
    },
    EventParticipantStatusEnum.CONFIRMED: {
        EventParticipantStatusEnum.REMOVED,
    },
}

NOTIFICATION_TYPE_BY_STATUS: dict[EventParticipantStatusEnum, NotificationTypeEnum] = {
    EventParticipantStatusEnum.CONFIRMED: NotificationTypeEnum.EVENT_REQUEST_APPROVED,
    EventParticipantStatusEnum.REJECTED: NotificationTypeEnum.EVENT_REQUEST_REJECTED,
    EventParticipantStatusEnum.REMOVED: NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED,
}


class EventRepository(Protocol):
    def add(self, event: NewEvent) -> Event: ...

    def find_existing_tag_ids(self, tag_ids: Collection[UUID]) -> set[UUID]: ...

    def get_by_id(self, event_id: UUID) -> Event | None: ...

    def get_participant(
        self, event_id: UUID, participant_id: UUID
    ) -> EventParticipant | None: ...

    def update_participant_status_and_notify(
        self,
        event_id: UUID,
        participant_id: UUID,
        new_status: EventParticipantStatusEnum,
        notification_type: NotificationTypeEnum,
    ) -> EventParticipant: ...


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
    """Raised when an event does not exist."""


class EventParticipantNotFoundError(Exception):
    """Raised when a participant does not exist in an event."""


class NotEventOrganizerError(Exception):
    """Raised when a non-organizer tries to manage event participants."""


class InvalidParticipantStatusTransitionError(Exception):
    """Raised when an invalid participant state transition is requested."""


class EventIsFullError(Exception):
    """Raised when approving a participant exceeds the event capacity."""


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

        if event.tag_ids:
            existing = self.repository.find_existing_tag_ids(event.tag_ids)
            if len(existing) != len(event.tag_ids):
                raise EventTagNotFoundError

        return self.repository.add(event)

    def update_participant_status(
        self,
        event_id: UUID,
        participant_id: UUID,
        new_status: EventParticipantStatusEnum,
        requester_id: UUID,
    ) -> EventParticipant:
        """Approve, reject, or remove an event participant."""
        event = self.repository.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError

        if event.event_creator_id != requester_id:
            raise NotEventOrganizerError

        participant = self.repository.get_participant(event_id, participant_id)
        if participant is None:
            raise EventParticipantNotFoundError

        allowed_next_statuses = VALID_TRANSITIONS.get(participant.status, set())
        if new_status not in allowed_next_statuses:
            raise InvalidParticipantStatusTransitionError

        notification_type = NOTIFICATION_TYPE_BY_STATUS.get(new_status)
        if notification_type is None:
            raise InvalidParticipantStatusTransitionError

        return self.repository.update_participant_status_and_notify(
            event_id=event_id,
            participant_id=participant_id,
            new_status=new_status,
            notification_type=notification_type,
        )
