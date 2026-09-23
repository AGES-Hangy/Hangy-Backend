from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, EventParticipantsPage
from app.domain.enums import EventParticipantStatusEnum, EventPrivacyEnum

DEFAULT_PARTICIPANTS_LIMIT = 20
MIN_PARTICIPANTS_LIMIT = 1
MAX_PARTICIPANTS_LIMIT = 100

LISTABLE_STATUSES = (
    EventParticipantStatusEnum.CONFIRMED,
    EventParticipantStatusEnum.PENDING,
)


class EventParticipantsRepository(Protocol):
    def get_event(self, event_id: UUID) -> Event | None: ...

    def get_viewer_status(
        self, event_id: UUID, viewer_id: UUID
    ) -> EventParticipantStatusEnum | None: ...

    def list_participants(
        self,
        event_id: UUID,
        status: EventParticipantStatusEnum,
        limit: int,
        cursor: str | None,
        include_pending_count: bool,
    ) -> EventParticipantsPage: ...


class EventNotFoundError(Exception):
    """Raised when the requested event does not exist or is not visible."""


class NotEventOrganizerError(Exception):
    """Raised when someone other than the organizer asks for pending participants."""


class InvalidParticipantStatusError(Exception):
    """Raised when the status filter is neither PENDING nor CONFIRMED."""


class EventParticipantsService:
    def __init__(self, repository: EventParticipantsRepository) -> None:
        self.repository = repository

    def list_participants(
        self,
        event_id: UUID,
        viewer_id: UUID,
        status: str | None,
        limit: int = DEFAULT_PARTICIPANTS_LIMIT,
        cursor: str | None = None,
    ) -> EventParticipantsPage:
        event = self.repository.get_event(event_id)
        if event is None:
            raise EventNotFoundError

        requested_status = EventParticipantStatusEnum.CONFIRMED
        if status is not None:
            if status not in LISTABLE_STATUSES:
                raise InvalidParticipantStatusError
            requested_status = EventParticipantStatusEnum(status)

        is_organizer = event.event_creator_id == viewer_id
        if requested_status is EventParticipantStatusEnum.PENDING and not is_organizer:
            raise NotEventOrganizerError

        if (
            requested_status is EventParticipantStatusEnum.CONFIRMED
            and not is_organizer
        ):
            viewer_status = self.repository.get_viewer_status(event_id, viewer_id)
            visible = (
                event.event_privacy is EventPrivacyEnum.PUBLIC
                or viewer_status is EventParticipantStatusEnum.CONFIRMED
            )
            if not visible:
                raise EventNotFoundError

        bounded_limit = max(MIN_PARTICIPANTS_LIMIT, min(limit, MAX_PARTICIPANTS_LIMIT))
        return self.repository.list_participants(
            event_id=event_id,
            status=requested_status,
            limit=bounded_limit,
            cursor=cursor,
            include_pending_count=is_organizer,
        )
