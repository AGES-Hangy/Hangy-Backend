from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Event, EventInviteLink, EventShare
from app.domain.enums import EventPrivacyEnum, EventStatusEnum


class EventShareRepository(Protocol):
    def get_for_share(self, event_id: UUID) -> Event | None: ...

    def get_invite_link(self, event_id: UUID) -> EventInviteLink | None: ...

    def get_invite_link_by_token(self, token: str) -> EventInviteLink | None: ...

    def get_by_id(self, event_id: UUID) -> Event | None: ...


class ShareableEventNotFoundError(Exception):
    """Raised when an event cannot be shared or is no longer visible."""


class InviteLinkExpiredError(Exception):
    """Raised when an invite-only event has no valid share link."""


class EventShareService:
    def __init__(
        self, repository: EventShareRepository, frontend_base_url: str
    ) -> None:
        self.repository = repository
        self.frontend_base_url = frontend_base_url.rstrip("/")

    def get_share(self, event_id: UUID) -> EventShare:
        event = self.repository.get_for_share(event_id)
        if event is None:
            raise ShareableEventNotFoundError

        url = f"hangy://event/{event_id}"
        web_url = f"{self.frontend_base_url}/e/{event_id}"
        if event.event_privacy is EventPrivacyEnum.INVITE_ONLY:
            invite_link = self.repository.get_invite_link(event_id)
            if invite_link is None:
                raise ShareableEventNotFoundError
            expires_at = self._as_utc(invite_link.expires_at)
            if expires_at <= datetime.now(UTC):
                raise InviteLinkExpiredError
            url = f"hangy://invite/{invite_link.token}"
            web_url = f"{self.frontend_base_url}/invite/{invite_link.token}"

        event_date = event.starts_at
        location_name = event.location_name
        if event.event_privacy is EventPrivacyEnum.PRIVATE:
            event_date = None
            location_name = None

        return EventShare(
            url=url,
            web_url=web_url,
            title=event.event_title,
            event_date=event_date,
            location_name=location_name,
            cover_photo_url=event.cover_photo_url,
        )

    def resolve_invite(self, token: str) -> Event:
        invite_link = self.repository.get_invite_link_by_token(token)
        if invite_link is None:
            raise ShareableEventNotFoundError

        expires_at = self._as_utc(invite_link.expires_at)
        if expires_at <= datetime.now(UTC):
            raise InviteLinkExpiredError

        event = self.repository.get_by_id(invite_link.event_id)
        if event is None or event.event_status is EventStatusEnum.CANCELLED:
            raise ShareableEventNotFoundError

        return event

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
