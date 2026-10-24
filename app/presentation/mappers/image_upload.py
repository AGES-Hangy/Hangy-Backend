from fastapi import UploadFile

from app.config import settings

__all__ = ["read_image_upload"]


async def read_image_upload(
    file: UploadFile, max_size_bytes: int = settings.image_max_size_bytes
) -> bytes:
    """Read at most the limit plus one byte before passing content to the service."""
    return await file.read(max_size_bytes + 1)
