from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import UserPhoto, UserPhotosPage
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    encode_cursor,
)

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
    ) -> list[UserPhoto]: ...


class UserPhotosService:
    def __init__(self, repository: UserPhotosRepository) -> None:
        self.repository = repository

    def get_user_photos(
        self,
        user_id: UUID,
        *,
        limit: int = DEFAULT_USER_PHOTOS_LIMIT,
        cursor: str | None = None,
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
        )

        has_more = len(photos) > limit
        items = photos[:limit]
        next_cursor = None
        if has_more:
            last = items[-1]
            next_cursor = encode_cursor(last.created_at, last.photo_id)

        return UserPhotosPage(items=tuple(items), next_cursor=next_cursor)
