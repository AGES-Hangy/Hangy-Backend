from app.domain.entities import Event, EventShare, User
from app.presentation.dtos import (
    CancelEventOutput,
    CreateEventOutput,
    EventCreatorOutput,
    EventShareOutput,
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
    def to_cancel_dto(event: Event) -> CancelEventOutput:
        if event.event_id is None:
            raise ValueError("A persisted event must have an id")
        return CancelEventOutput(
            event_id=event.event_id,
            status=event.event_status,
            updated_at=event.updated_at,
        )

    @staticmethod
    def to_share_dto(share: EventShare) -> EventShareOutput:
        return EventShareOutput(
            url=share.url,
            web_url=share.web_url,
            title=share.title,
            event_date=share.event_date,
            location_name=share.location_name,
            cover_photo_url=share.cover_photo_url,
        )
