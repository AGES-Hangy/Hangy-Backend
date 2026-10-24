"""Image validation shared by event covers and experience photos."""

from typing import Protocol
from uuid import uuid4

from app.config import settings

__all__ = [
    "ImageStorage",
    "ImageStorageUnavailableError",
    "ImageTooLargeError",
    "ImageUploadService",
    "UnsupportedImageTypeError",
]


class UnsupportedImageTypeError(Exception):
    """The content is empty or is not JPG/PNG (HTTP 415)."""


class ImageTooLargeError(Exception):
    """The image exceeds the configured size limit (HTTP 413)."""


class ImageStorageUnavailableError(Exception):
    """Storage is unconfigured or an AWS operation failed (HTTP 503)."""


class ImageStorage(Protocol):
    def upload(self, key: str, content: bytes, content_type: str) -> str: ...

    def delete(self, url: str) -> None: ...

    def owns(self, url: str) -> bool: ...


class ImageUploadService:
    def __init__(
        self, storage: ImageStorage, max_size_bytes: int = settings.image_max_size_bytes
    ) -> None:
        self.storage = storage
        self.max_size_bytes = max_size_bytes

    def upload(self, folder: str, content: bytes, content_type: str) -> str:
        if len(content) > self.max_size_bytes:
            raise ImageTooLargeError("Image too large")
        # The client-provided MIME type is deliberately ignored.
        if content.startswith(b"\xff\xd8\xff"):
            extension, detected_type = "jpg", "image/jpeg"
        elif content.startswith(b"\x89PNG"):
            extension, detected_type = "png", "image/png"
        else:
            raise UnsupportedImageTypeError("Unsupported image type")
        key = f"{folder}/{uuid4()}.{extension}"
        return self.storage.upload(key, content, detected_type)

    def delete(self, url: str) -> None:
        self.storage.delete(url)

    def owns(self, url: str) -> bool:
        return self.storage.owns(url)
