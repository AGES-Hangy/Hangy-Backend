"""Private S3 access. Callers own user authorization and object key selection."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import BinaryIO

from boto3.exceptions import S3UploadFailedError
from botocore.exceptions import BotoCoreError, ClientError

from app.config import settings
from app.infrastructure.storage.s3 import _create_s3_client


class StorageError(RuntimeError):
    """Storage configuration, credentials, or operation failed."""


class StorageNotFoundError(StorageError):
    """The requested object does not exist."""


@dataclass(frozen=True, slots=True)
class StoragePage:
    keys: tuple[str, ...]
    next_token: str | None


@contextmanager
def _storage_operation() -> Iterator[None]:
    try:
        yield
    except ClientError as exc:
        if exc.response["Error"]["Code"] in {"NoSuchKey", "NotFound", "404"}:
            raise StorageNotFoundError("Storage object not found") from exc
        raise StorageError("S3 operation failed") from exc
    except (BotoCoreError, S3UploadFailedError) as exc:
        raise StorageError("S3 operation failed") from exc


def _validate_key(key: str) -> None:
    if not key or len(key.encode("utf-8")) > 1024:
        raise ValueError("Object key must contain between 1 and 1024 UTF-8 bytes")


class S3Storage:
    """Synchronous adapter; use in sync routes/services or a worker thread.

    Uses the AWS SDK credential chain (EC2 role in production). Construction is
    explicit, so importing the application never contacts AWS. Invalid method
    arguments raise ValueError; AWS failures raise StorageError.
    """

    def __init__(self) -> None:
        self.bucket_name = settings.s3_bucket_name
        if not self.bucket_name or not settings.aws_region:
            raise StorageError("Configure S3_BUCKET_NAME and AWS_REGION")
        with _storage_operation():
            self._client = _create_s3_client(settings.aws_region)

    def upload_file(
        self,
        key: str,
        file: BinaryIO,
        *,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload from the current stream position, including multipart uploads."""
        _validate_key(key)
        with _storage_operation():
            self._client.upload_fileobj(
                file, self.bucket_name, key, ExtraArgs={"ContentType": content_type}
            )

    def download_file(self, key: str, file: BinaryIO) -> None:
        """Write to a binary stream without loading the entire object in memory."""
        _validate_key(key)
        with _storage_operation():
            self._client.download_fileobj(self.bucket_name, key, file)

    def delete_file(self, key: str) -> None:
        """Delete an object; deleting an absent key is also successful."""
        _validate_key(key)
        with _storage_operation():
            self._client.delete_object(Bucket=self.bucket_name, Key=key)

    def list_files(
        self, *, prefix: str, limit: int = 100, continuation_token: str | None = None
    ) -> StoragePage:
        """Return one bounded page. The caller must authorize the prefix."""
        if len(prefix.encode("utf-8")) > 1024 or not 1 <= limit <= 1000:
            raise ValueError("Prefix must be at most 1024 bytes and limit 1 to 1000")
        params = {"Bucket": self.bucket_name, "Prefix": prefix, "MaxKeys": limit}
        if continuation_token is not None:
            if not continuation_token or len(continuation_token) > 8192:
                raise ValueError("Invalid continuation token")
            params["ContinuationToken"] = continuation_token
        with _storage_operation():
            response = self._client.list_objects_v2(**params)
        return StoragePage(
            keys=tuple(item["Key"] for item in response.get("Contents", [])),
            next_token=response.get("NextContinuationToken"),
        )

    def generate_download_url(self, key: str, *, expires_in: int = 900) -> str:
        """Sign a GET URL; this does not check existence or user authorization.

        Temporary AWS credentials may expire before the requested URL lifetime.
        """
        _validate_key(key)
        if not 1 <= expires_in <= 604800:
            raise ValueError("URL lifetime must be between 1 and 604800 seconds")
        with _storage_operation():
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expires_in,
            )
