import secrets
from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, EventInviteLink, NewEventInviteLink
from app.domain.enums import EventPrivacyEnum

# secrets.token_urlsafe(32) yields a 43-char opaque token - unguessable and
# never derived from the event_id or a sequential id.
INVITE_TOKEN_BYTES = 32


class EventPrivacyRepository(Protocol):
    def get_event(self, event_id: UUID) -> Event | None: ...

    def add_invite_link(self, invite_link: NewEventInviteLink) -> EventInviteLink: ...


class EventNotFoundError(Exception):
    """Raised when the referenced event does not exist or is not visible."""


class NotEventOrganizerError(Exception):
    """Raised when someone other than the organizer manages the event's privacy."""


class EventNotInviteOnlyError(Exception):
    """Raised when an invite link is requested for an event that isn't INVITE_ONLY."""


class EventPrivacyService:
    def __init__(self, repository: EventPrivacyRepository) -> None:
        self.repository = repository

    def create_invite_link(self, event_id: UUID, requester_id: UUID) -> EventInviteLink:
        """Generate an opaque, single-use invite link for an INVITE_ONLY event."""
        event = self.repository.get_event(event_id)
        if event is None:
            raise EventNotFoundError
        if event.event_creator_id != requester_id:
            raise NotEventOrganizerError
        if event.event_privacy is not EventPrivacyEnum.INVITE_ONLY:
            raise EventNotInviteOnlyError

        return self.repository.add_invite_link(
            NewEventInviteLink(
                event_id=event_id,
                token=secrets.token_urlsafe(INVITE_TOKEN_BYTES),
                created_by=requester_id,
                # A link can never outlive the event it invites people to.
                expires_at=event.starts_at,
            )
        )
