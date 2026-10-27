import logging
from typing import Protocol
from uuid import UUID

from app.domain.services.image_upload import ImageUploadService

__all__ = [
    "ProfilePhotoRepository",
    "ProfilePhotoService",
    "ProfilePhotoUserNotFoundError",
]

logger = logging.getLogger(__name__)


class ProfilePhotoRepository(Protocol):
    def set_profile_photo(
        self, user_id: UUID, photo_url: str
    ) -> tuple[bool, str | None]: ...


class ProfilePhotoUserNotFoundError(Exception):
    """The account no longer exists (deleted between the token and the upload)."""


class ProfilePhotoService:
    def __init__(
        self,
        repository: ProfilePhotoRepository,
        image_upload_service: ImageUploadService,
    ) -> None:
        self.repository = repository
        self.image_upload_service = image_upload_service

    def replace(self, user_id: UUID, content: bytes, content_type: str) -> str:
        """Store the new photo and drop the previous object from S3."""
        photo_url = self.image_upload_service.upload(
            folder=f"profile-photos/{user_id}",
            content=content,
            content_type=content_type,
        )
        try:
            exists, previous = self.repository.set_profile_photo(user_id, photo_url)
        except Exception:
            self._delete_quietly(photo_url)
            raise
        if not exists:
            self._delete_quietly(photo_url)
            raise ProfilePhotoUserNotFoundError
        if previous and previous != photo_url:
            self._delete_quietly(previous)
        return photo_url

    def _delete_quietly(self, url: str) -> None:
        try:
            if self.image_upload_service.owns(url):
                self.image_upload_service.delete(url)
        except Exception:
            logger.exception("Failed to delete S3 object %s", url)
