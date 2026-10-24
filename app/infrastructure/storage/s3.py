"""S3 adapter returning stable public image URLs, with lazy SDK creation."""

from urllib.parse import quote, unquote, urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.domain.services.image_upload import ImageStorageUnavailableError

__all__ = ["S3ImageStorage", "get_image_storage"]


def _create_s3_client(region: str):
    return boto3.client(
        "s3",
        region_name=region,
        config=Config(
            signature_version="s3v4",
            connect_timeout=5,
            read_timeout=30,
            retries={"mode": "standard", "total_max_attempts": 3},
        ),
    )


class S3ImageStorage:
    def __init__(self) -> None:
        self.bucket_name = settings.aws_s3_bucket
        self.public_base_url = settings.s3_public_base_url.rstrip("/")
        self._client = None

    def _get_client(self):
        if not self.bucket_name:
            raise ImageStorageUnavailableError("Image storage unavailable")
        if self._client is None:
            self._client = _create_s3_client(settings.aws_region)
        return self._client

    def upload(self, key: str, content: bytes, content_type: str) -> str:
        try:
            self._get_client().put_object(
                Bucket=self.bucket_name, Key=key, Body=content, ContentType=content_type
            )
        except (BotoCoreError, ClientError) as exc:
            raise ImageStorageUnavailableError("Image storage unavailable") from exc
        return f"{self.public_base_url}/{quote(key, safe='/')}"

    def _key(self, url: str) -> str | None:
        if not self.bucket_name or not self.public_base_url:
            return None
        try:
            parsed, base = urlsplit(url), urlsplit(self.public_base_url)
        except ValueError:
            return None
        prefix = base.path + "/"
        if (
            parsed.scheme != base.scheme
            or parsed.netloc != base.netloc
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(prefix)
        ):
            return None
        key = unquote(parsed.path[len(prefix) :])
        if not key or any(part in {"", ".", ".."} for part in key.split("/")):
            return None
        return key

    def owns(self, url: str) -> bool:
        return self._key(url) is not None

    def delete(self, url: str) -> None:
        key = self._key(url)
        # Never turn an unrelated URL into a key in this bucket.
        if key is None:
            return
        try:
            self._get_client().delete_object(Bucket=self.bucket_name, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"NoSuchKey", "NotFound", "404"}:
                raise ImageStorageUnavailableError("Image storage unavailable") from exc
        except BotoCoreError as exc:
            raise ImageStorageUnavailableError("Image storage unavailable") from exc


def get_image_storage() -> S3ImageStorage:
    """FastAPI dependency; creating it never resolves credentials or calls AWS."""
    return S3ImageStorage()
