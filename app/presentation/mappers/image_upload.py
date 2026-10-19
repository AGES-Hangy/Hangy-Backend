from fastapi import UploadFile

from app.config import settings
from app.domain.services.image_upload import ImageTooLargeError

__all__ = ["read_image_upload"]


async def read_image_upload(
    file: UploadFile, max_size_bytes: int = settings.image_max_size_bytes
) -> bytes:
    """Read at most the limit plus one byte before passing content to the service."""
    content = await file.read(max_size_bytes + 1)
    if len(content) > max_size_bytes:
        raise ImageTooLargeError("Image too large")
    return content
