from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    EventExperience,
    EventExperienceAccess,
    NewEventExperience,
)
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)

__all__ = [
    "ExperienceAlreadyExistsError",
    "ExperienceEventNotFinishedError",
    "ExperienceEventNotFoundError",
    "ExperienceParticipantNotConfirmedError",
    "ExperienceRepository",
    "ExperienceService",
]


class ExperienceRepository(Protocol):
    def get_access_for_update(
        self, event_id: UUID, user_id: UUID
    ) -> EventExperienceAccess | None: ...

    def add(
        self, participant_id: UUID, experience: NewEventExperience
    ) -> EventExperience | None: ...


class ExperienceEventNotFoundError(Exception):
    """The event does not exist or is not visible to this user."""


class ExperienceEventNotFinishedError(Exception):
    """The event is still in progress."""


class ExperienceParticipantNotConfirmedError(Exception):
    """The user is not a confirmed participant in this event."""


class ExperienceAlreadyExistsError(Exception):
    """A participant can create only one experience per event."""


class ExperienceService:
    def __init__(self, repository: ExperienceRepository) -> None:
        self.repository = repository

    def create(
        self, event_id: UUID, user_id: UUID, experience: NewEventExperience
    ) -> EventExperience:
        access = self.repository.get_access_for_update(event_id, user_id)
        if access is None:
            raise ExperienceEventNotFoundError

        event = access.event
        participant = access.participant
        confirmed = (
            participant is not None
            and participant.status is EventParticipantStatusEnum.CONFIRMED
        )
        if (
            access.organizer_blocked_viewer
            or event.event_status in (EventStatusEnum.DRAFT, EventStatusEnum.CANCELLED)
            or (
                event.event_privacy is EventPrivacyEnum.INVITE_ONLY
                and user_id != event.event_creator_id
                and not confirmed
            )
        ):
            raise ExperienceEventNotFoundError
        if not confirmed or participant.participant_id is None:
            raise ExperienceParticipantNotConfirmedError

        ends_at = event.ends_at
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=UTC)
        if (
            event.event_status is not EventStatusEnum.FINISHED
            and ends_at > datetime.now(UTC)
        ):
            raise ExperienceEventNotFinishedError

        created = self.repository.add(participant.participant_id, experience)
        if created is None:
            raise ExperienceAlreadyExistsError
        return created
