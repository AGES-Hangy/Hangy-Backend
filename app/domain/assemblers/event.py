from app.domain.entities import Event, EventParticipant, User
from app.presentation.dtos import (
    CancelEventOutput,
    CreateEventOutput,
    EventCreatorOutput,
    UpdateEventOutput,
    UpdateEventParticipantOutput,
)


class EventAssembler:
    """Build event response DTOs from domain entities."""

    @staticmethod
    def to_created_dto(event: Event, creator: User) -> CreateEventOutput:
        if event.event_id is None:
            raise ValueError("A persisted event must have an id")
        if creator.user_id is None:
            raise ValueError("A persisted user must have an id")
        return CreateEventOutput(
            event_id=event.event_id,
            title=event.event_title,
            status=event.event_status,
            privacy=event.event_privacy,
            event_date=event.starts_at,
            creator=EventCreatorOutput(id=creator.user_id, name=creator.name),
        )

    @staticmethod
    def to_participant_updated_dto(
        participant: EventParticipant,
    ) -> UpdateEventParticipantOutput:
        if participant.participant_id is None:
            raise ValueError("A persisted participant must have an id")
        return UpdateEventParticipantOutput(
            participant_id=participant.participant_id,
            status=participant.status,
            updated_at=participant.updated_at,
        )

    @staticmethod
    def to_cancel_dto(event: Event) -> CancelEventOutput:
        if event.event_id is None:
            raise ValueError("A persisted event must have an id")
        return CancelEventOutput(
            event_id=event.event_id,
            status=event.event_status,
            updated_at=event.updated_at,
        )

    @staticmethod
    def to_updated_dto(event: Event) -> UpdateEventOutput:
        if event.event_id is None:
            raise ValueError("A persisted event must have an id")
        return UpdateEventOutput(
            event_id=event.event_id,
            title=event.event_title,
            event_date=event.starts_at,
            status=event.event_status,
            updated_at=event.updated_at,
        )
