from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, EventParticipant
from app.domain.enums import EventParticipantStatusEnum, EventStatusEnum
from app.domain.services.event import EventAlreadyFinishedError

__all__ = [
    "CancelParticipationRepository",
    "CancelParticipationService",
    "ParticipationNotFoundError",
    "RequestAlreadyAnsweredError",
]


class CancelParticipationRepository(Protocol):
    def get_event_for_update(self, event_id: UUID) -> Event | None: ...

    def get_participant_for_update(
        self, event_id: UUID, user_id: UUID
    ) -> EventParticipant | None: ...

    def cancel(self, event_id: UUID, user_id: UUID) -> None: ...


class ParticipationNotFoundError(Exception):
    """There is no participation to cancel for this user and event."""


class RequestAlreadyAnsweredError(Exception):
    """The organizer has already rejected or removed the participation."""


class CancelParticipationService:
    def __init__(self, repository: CancelParticipationRepository) -> None:
        self.repository = repository

    def cancel(self, event_id: UUID, user_id: UUID) -> None:
        # Match the event -> participant lock order used by organizer updates
        # and task 105. Inspect current state only after acquiring both locks.
        event = self.repository.get_event_for_update(event_id)
        if event is None:
            raise ParticipationNotFoundError
        participant = self.repository.get_participant_for_update(event_id, user_id)
        if (
            participant is None
            or participant.status is EventParticipantStatusEnum.CANCELLED
        ):
            raise ParticipationNotFoundError
        if participant.status not in (
            EventParticipantStatusEnum.PENDING,
            EventParticipantStatusEnum.CONFIRMED,
        ):
            raise RequestAlreadyAnsweredError
        if participant.status is EventParticipantStatusEnum.CONFIRMED:
            ends_at = event.ends_at
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=UTC)
            if (
                event.event_status is EventStatusEnum.FINISHED
                or ends_at <= datetime.now(UTC)
            ):
                raise EventAlreadyFinishedError
        self.repository.cancel(event_id, user_id)
