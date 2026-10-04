from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.domain.entities import EventInviteLink, EventParticipant


class InviteAcceptanceOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    EVENT_FULL = "EVENT_FULL"
    EVENT_NOT_FOUND = "EVENT_NOT_FOUND"
    PARTICIPANT_EXISTS = "PARTICIPANT_EXISTS"


@dataclass(frozen=True, slots=True)
class InviteAcceptance:
    outcome: InviteAcceptanceOutcome
    participant: EventParticipant | None = None


class InviteRepository(Protocol):
    def get_by_token(self, token: str) -> EventInviteLink | None: ...

    def accept(self, invite: EventInviteLink, user_id: UUID) -> InviteAcceptance: ...


class InviteLinkNotFoundError(Exception):
    """Raised when an invite token does not identify an invite link."""


class InviteLinkExpiredError(Exception):
    """Raised when an invite link has expired."""


class InviteEventNotFoundError(Exception):
    """Raised when the event behind an invite is no longer available."""


class InviteEventFullError(Exception):
    """Raised when confirming through an invite would exceed capacity."""


class InviteAlreadyAcceptedError(Exception):
    """Raised when the user already participates in the invited event."""


class InviteService:
    def __init__(self, repository: InviteRepository) -> None:
        self.repository = repository

    def accept(self, token: str, user_id: UUID) -> EventParticipant:
        invite = self.repository.get_by_token(token)
        if invite is None:
            raise InviteLinkNotFoundError
        if self._as_utc(invite.expires_at) <= datetime.now(UTC):
            raise InviteLinkExpiredError

        result = self.repository.accept(invite, user_id)
        if result.outcome is InviteAcceptanceOutcome.EVENT_NOT_FOUND:
            raise InviteEventNotFoundError
        if result.outcome is InviteAcceptanceOutcome.EVENT_FULL:
            raise InviteEventFullError
        if result.outcome is InviteAcceptanceOutcome.PARTICIPANT_EXISTS:
            raise InviteAlreadyAcceptedError
        if result.participant is None:
            raise ValueError("An accepted invite must return a participant")
        return result.participant

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
