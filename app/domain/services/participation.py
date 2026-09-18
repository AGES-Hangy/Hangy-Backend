from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, EventParticipant
from app.domain.enums import EventParticipantStatusEnum, EventPrivacyEnum


class ParticipationRepository(Protocol):
    def get_event(self, event_id: UUID) -> Event | None: ...

    def get_existing_participant(
        self, event_id: UUID, user_id: UUID
    ) -> EventParticipant | None: ...

    def get_organizer_id(self, event_id: UUID) -> UUID | None: ...

    def join(
        self,
        event_id: UUID,
        user_id: UUID,
        status: EventParticipantStatusEnum,
    ) -> EventParticipant: ...


class EventNotFoundError(Exception):
    """Raised when the requested event does not exist."""


class AlreadyParticipatingError(Exception):
    """Raised when the user already has a participation record for the event."""


class OrganizerCannotJoinError(Exception):
    """Raised when the event organizer tries to join their own event."""


class ParticipationService:
    def __init__(self, repository: ParticipationRepository) -> None:
        self.repository = repository

    def request_or_join(self, event_id: UUID, user_id: UUID) -> EventParticipant:
        event = self.repository.get_event(event_id)
        if event is None:
            raise EventNotFoundError

        if event.event_creator_id == user_id:
            raise OrganizerCannotJoinError

        existing = self.repository.get_existing_participant(event_id, user_id)
        if existing is not None:
            raise AlreadyParticipatingError

        status = (
            EventParticipantStatusEnum.CONFIRMED
            if event.event_privacy is EventPrivacyEnum.PUBLIC
            else EventParticipantStatusEnum.PENDING
        )
        return self.repository.join(event_id, user_id, status)
