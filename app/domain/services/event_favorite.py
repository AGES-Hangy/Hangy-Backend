from typing import Protocol
from uuid import UUID

from app.domain.entities import EventDetails, EventFavorite, User
from app.domain.enums import EventStatusEnum, UserTypeEnum
from app.domain.services.event_details import (
    EventCancelledError,
    EventDetailsNotFoundError,
)


class EventFavoriteRepository(Protocol):
    def add(self, favorite: EventFavorite) -> None: ...

    def remove(self, favorite: EventFavorite) -> None: ...


class EventVisibility(Protocol):
    """What GET /events/{event_id} answers, so both share one visibility rule."""

    def get_details(self, event_id: UUID, viewer_id: UUID) -> EventDetails: ...


class OnlyPersonalAccountsCanFavoriteError(Exception):
    """Raised when a business account tries to favorite an event."""


class FavoriteEventNotFoundError(Exception):
    """Raised when the event does not exist or cannot be favorited by the user."""


class EventFavoriteService:
    def __init__(
        self,
        repository: EventFavoriteRepository,
        event_visibility: EventVisibility,
    ) -> None:
        self.repository = repository
        self.event_visibility = event_visibility

    def favorite(self, user: User, event_id: UUID) -> None:
        self.repository.add(self._favorite_for(user, event_id))

    def unfavorite(self, user: User, event_id: UUID) -> None:
        self.repository.remove(self._favorite_for(user, event_id))

    def _favorite_for(self, user: User, event_id: UUID) -> EventFavorite:
        if user.user_id is None:
            raise ValueError("A persisted user must have an id")
        if user.user_type is not UserTypeEnum.PERSONAL:
            raise OnlyPersonalAccountsCanFavoriteError

        try:
            details = self.event_visibility.get_details(event_id, user.user_id)
        except (EventDetailsNotFoundError, EventCancelledError) as error:
            raise FavoriteEventNotFoundError from error
        # The organizer can open their own draft, but a draft is not yet an
        # event anyone can be interested in.
        if details.event.event_status is EventStatusEnum.DRAFT:
            raise FavoriteEventNotFoundError

        return EventFavorite(user_id=user.user_id, event_id=event_id)
