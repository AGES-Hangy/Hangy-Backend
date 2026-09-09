from app.domain.entities import Event, EventInviteLink, User
from app.presentation.dtos import (
    CancelEventOutput,
    CreateEventOutput,
    CreateInviteLinkOutput,
    EventCreatorOutput,
    UpdateEventOutput,
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
    def to_invite_link_dto(
        invite_link: EventInviteLink, base_url: str
    ) -> CreateInviteLinkOutput:
        if invite_link.invite_id is None:
            raise ValueError("A persisted invite link must have an id")
        return CreateInviteLinkOutput(
            invite_id=invite_link.invite_id,
            token=invite_link.token,
            url=f"{base_url}{invite_link.token}",
            expires_at=invite_link.expires_at,
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
