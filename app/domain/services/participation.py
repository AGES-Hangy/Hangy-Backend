from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, EventParticipant
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)


class ParticipationRepository(Protocol):
    def get_event_for_update(self, event_id: UUID) -> Event | None: ...

    def get_existing_participant_for_update(
        self, event_id: UUID, user_id: UUID
    ) -> EventParticipant | None: ...

    def count_confirmed(self, event_id: UUID) -> int: ...

    def upsert_participation(
        self,
        event_id: UUID,
        user_id: UUID,
        organizer_id: UUID,
        status: EventParticipantStatusEnum,
        existing_participant_id: UUID | None,
    ) -> EventParticipant: ...


class EventNotFoundError(Exception):
    """Raised when the requested event does not exist or is not visible."""


class InviteOnlyEventError(Exception):
    """Raised when participation is requested for an invite-only event."""


class EventAlreadyFinishedError(Exception):
    """Raised when the event has already finished."""


class EventIsFullError(Exception):
    """Raised when the event has reached its confirmed-participant capacity."""


class RequestAlreadyPendingError(Exception):
    """Raised when the user already has an open request for this event."""


class AlreadyParticipatingError(Exception):
    """Raised when the user is already a confirmed participant of this event."""


class OrganizerCannotJoinError(Exception):
    """Raised when the event organizer tries to join their own event."""


class ParticipationService:
    def __init__(self, repository: ParticipationRepository) -> None:
        self.repository = repository

    def request_or_join(self, event_id: UUID, user_id: UUID) -> EventParticipant:
        # Locking the event first serializes every call for this event_id,
        # including the capacity check below - two concurrent confirmations
        # can't both see room for the same last spot.
        event = self.repository.get_event_for_update(event_id)
        if event is None:
            raise EventNotFoundError

        if event.event_privacy is EventPrivacyEnum.INVITE_ONLY:
            raise InviteOnlyEventError

        if event.event_status is EventStatusEnum.FINISHED:
            raise EventAlreadyFinishedError

        if event.event_creator_id == user_id:
            raise OrganizerCannotJoinError

        existing = self.repository.get_existing_participant_for_update(
            event_id, user_id
        )
        if existing is not None:
            if existing.status is EventParticipantStatusEnum.PENDING:
                raise RequestAlreadyPendingError
            if existing.status is EventParticipantStatusEnum.CONFIRMED:
                raise AlreadyParticipatingError
            # CANCELLED, REJECTED or REMOVED: falls through and reuses the
            # same row via upsert_participation, per the UNIQUE(user_id,
            # event_id) constraint - a brand new confirmation/request just
            # updates it instead of inserting a new line.

        # Capacity is checked the same way for a direct confirmation and for
        # a request: if there's no room left to eventually approve someone,
        # a new pending request doesn't make sense either.
        if event.max_participants is not None:
            confirmed_count = self.repository.count_confirmed(event_id)
            if confirmed_count >= event.max_participants:
                raise EventIsFullError

        target_status = (
            EventParticipantStatusEnum.CONFIRMED
            if event.event_privacy is EventPrivacyEnum.PUBLIC
            else EventParticipantStatusEnum.PENDING
        )
        return self.repository.upsert_participation(
            event_id=event_id,
            user_id=user_id,
            organizer_id=event.event_creator_id,
            status=target_status,
            existing_participant_id=(
                existing.participant_id if existing is not None else None
            ),
        )
