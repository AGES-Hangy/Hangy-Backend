from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from app.domain.entities import UserEventsPage
from app.domain.enums import EventPrivacyEnum, EventStatusEnum
from app.domain.services.auth import UserRepository
from app.domain.services.user_tags import UserNotFoundError

DEFAULT_USER_EVENTS_LIMIT = 20
MIN_USER_EVENTS_LIMIT = 1
MAX_USER_EVENTS_LIMIT = 50
MAX_USER_EVENTS_CURSOR_LENGTH = 200

# What someone else sees on a profile. Past events are listed too, so FINISHED
# stays alongside PUBLISHED; DRAFT and CANCELLED never leave the owner's view.
PUBLIC_PROFILE_PRIVACIES = (EventPrivacyEnum.PUBLIC,)
PUBLIC_PROFILE_STATUSES = (EventStatusEnum.PUBLISHED, EventStatusEnum.FINISHED)


class UserEventsRepository(Protocol):
    def user_blocked_viewer(self, user_id: UUID, viewer_id: UUID) -> bool: ...

    def list_events(
        self,
        user_id: UUID,
        viewer_id: UUID,
        privacies: Collection[EventPrivacyEnum] | None,
        statuses: Collection[EventStatusEnum] | None,
        limit: int,
        cursor: str | None,
    ) -> UserEventsPage: ...


class UserEventsService:
    """List the events a user created or confirmed presence in."""

    def __init__(
        self,
        user_repository: UserRepository,
        repository: UserEventsRepository,
    ) -> None:
        self.user_repository = user_repository
        self.repository = repository

    def get_user_events(
        self,
        user_id: UUID,
        viewer_id: UUID,
        limit: int = DEFAULT_USER_EVENTS_LIMIT,
        cursor: str | None = None,
    ) -> UserEventsPage:
        is_owner = user_id == viewer_id
        if not is_owner:
            user = self.user_repository.get_by_id(user_id)
            # A block answers exactly like a missing account: telling them
            # apart would confirm to the blocked viewer that the profile exists.
            if (
                user is None
                or user.deleted_at is not None
                or self.repository.user_blocked_viewer(user_id, viewer_id)
            ):
                raise UserNotFoundError

        return self.repository.list_events(
            user_id=user_id,
            viewer_id=viewer_id,
            # None leaves the filter out: owners see all of their own events.
            privacies=None if is_owner else PUBLIC_PROFILE_PRIVACIES,
            statuses=None if is_owner else PUBLIC_PROFILE_STATUSES,
            limit=limit,
            cursor=cursor,
        )
