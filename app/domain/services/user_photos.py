from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import UserPhoto, UserPhotosPage
from app.domain.enums import UserTypeEnum
from app.domain.services.auth import UserRepository
from app.domain.services.block import BlockChecker
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)
from app.domain.services.users import UserNotFoundError

DEFAULT_USER_PHOTOS_LIMIT = 30
MIN_USER_PHOTOS_LIMIT = 1
MAX_USER_PHOTOS_LIMIT = 100


class UserPhotosRepository(Protocol):
    def list_for_user(
        self,
        user_id: UUID,
        *,
        limit: int,
        cursor_created_at: datetime | None,
        cursor_photo_id: UUID | None,
        public_only: bool = False,
        by_organizer: bool = False,
    ) -> list[UserPhoto]: ...

    def are_connected(self, user_id: UUID, other_id: UUID) -> bool: ...


class UserPhotosForbiddenError(Exception):
    """Raised when a visitor who is not a connection opens a personal gallery."""


class UserPhotosService:
    def __init__(
        self,
        repository: UserPhotosRepository,
        user_repository: UserRepository | None = None,
        block_checker: BlockChecker | None = None,
    ) -> None:
        self.repository = repository
        self.user_repository = user_repository
        self.block_checker = block_checker

    def get_user_photos(
        self,
        user_id: UUID,
        *,
        limit: int = DEFAULT_USER_PHOTOS_LIMIT,
        cursor: str | None = None,
        public_only: bool = False,
        by_organizer: bool = False,
    ) -> UserPhotosPage:
        if not MIN_USER_PHOTOS_LIMIT <= limit <= MAX_USER_PHOTOS_LIMIT:
            raise InvalidPaginationError(
                f"limit must be between {MIN_USER_PHOTOS_LIMIT} "
                f"and {MAX_USER_PHOTOS_LIMIT}"
            )

        cursor_created_at: datetime | None = None
        cursor_photo_id: UUID | None = None
        if cursor:
            cursor_created_at, cursor_photo_id = decode_cursor(cursor)

        photos = self.repository.list_for_user(
            user_id,
            limit=limit + 1,
            cursor_created_at=cursor_created_at,
            cursor_photo_id=cursor_photo_id,
            public_only=public_only,
            by_organizer=by_organizer,
        )

        has_more = len(photos) > limit
        items = photos[:limit]
        next_cursor = None
        if has_more:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at, last.photo_id)

        return UserPhotosPage(items=tuple(items), next_cursor=next_cursor)

    def get_profile_photos(
        self,
        user_id: UUID,
        viewer_id: UUID,
        *,
        limit: int = DEFAULT_USER_PHOTOS_LIMIT,
        cursor: str | None = None,
    ) -> UserPhotosPage:
        """The Gallery tab of a profile, as `viewer_id` may see it.

        A person's gallery holds the photos they published and only their
        connections see it; a business gallery holds the photos published on
        the events it organized, and anyone sees it.
        """
        assert self.user_repository is not None and self.block_checker is not None
        user = self.user_repository.get_by_id(user_id)
        # Same rule as GET /users/{user_id}: a block hides the profile from both
        # sides, with the error of a missing account.
        if (
            user is None
            or user.deleted_at is not None
            or self.block_checker.is_blocked_between(user_id, viewer_id)
        ):
            raise UserNotFoundError
        is_owner = viewer_id == user_id
        is_business = user.user_type != UserTypeEnum.PERSONAL
        if (
            not is_owner
            and not is_business
            and not self.repository.are_connected(user_id, viewer_id)
        ):
            raise UserPhotosForbiddenError
        return self.get_user_photos(
            user_id,
            limit=limit,
            cursor=cursor,
            public_only=not is_owner,
            by_organizer=is_business,
        )
