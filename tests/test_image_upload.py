import asyncio
import runpy
from dataclasses import replace
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import UUID

import boto3
import pytest
from botocore.exceptions import EndpointConnectionError, NoCredentialsError
from botocore.stub import Stubber
from fastapi import UploadFile

from app.domain.services import (
    ImageStorageUnavailableError,
    ImageTooLargeError,
    ImageUploadService,
    UnsupportedImageTypeError,
)
from app.infrastructure.storage import S3ImageStorage, get_image_storage
from app.infrastructure.storage import s3 as module
from app.presentation.mappers import read_image_upload

LIMIT = 5242880
BASE = "https://hangy-test-images.s3.us-east-1.amazonaws.com"


def stored_images(storage, prefix):
    client = storage._get_client()
    objects = {}
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=storage.bucket_name, Prefix=prefix
    ):
        for obj in page.get("Contents", []):
            response = client.get_object(Bucket=storage.bucket_name, Key=obj["Key"])
            with response["Body"] as body:
                objects[f"{storage.public_base_url}/{obj['Key']}"] = (
                    body.read(),
                    response["ContentType"],
                )
    return objects


@pytest.mark.parametrize(
    ("content", "header", "extension", "mime", "folder"),
    [
        (b"\xff\xd8\xffimage", "image/png", "jpg", "image/jpeg", "events/covers"),
        (b"\x89PNGimage", "text/plain", "png", "image/png", "experiences/123"),
    ],
)
def test_upload_detects_content_and_generates_uuid_key(
    live_image_storage, content, header, extension, mime, folder
):
    storage, prefix = live_image_storage
    service = ImageUploadService(storage)
    folder = prefix + folder
    url = service.upload(folder, content, header)
    assert url.startswith(f"{storage.public_base_url}/{folder}/")
    name = url.rsplit("/", 1)[1]
    assert name.endswith("." + extension)
    assert UUID(name.split(".")[0]).version == 4
    assert stored_images(storage, prefix) == {url: (content, mime)}
    assert service.owns(url)
    assert not service.owns("https://external.test/photo.png")
    service.delete(url)
    service.delete(url)
    assert stored_images(storage, prefix) == {}


@pytest.mark.parametrize("content", [b"", b"text renamed to .png", b"GIF89a"])
def test_invalid_content_does_not_write(live_image_storage, content):
    storage, prefix = live_image_storage
    with pytest.raises(UnsupportedImageTypeError, match="Unsupported image type"):
        ImageUploadService(storage).upload(
            prefix + "events/covers", content, "image/png"
        )
    assert stored_images(storage, prefix) == {}


def test_size_boundary_and_no_write_above_limit(live_image_storage):
    storage, prefix = live_image_storage
    service = ImageUploadService(storage, max_size_bytes=LIMIT)
    content = b"\x89PNG" + bytes(LIMIT - 4)
    url = service.upload(prefix + "events/covers", content, "image/png")
    assert stored_images(storage, prefix)[url] == (content, "image/png")
    with pytest.raises(ImageTooLargeError, match="Image too large"):
        service.upload(prefix + "events/covers", content + b"x", "image/png")
    assert len(stored_images(storage, prefix)) == 1


def test_read_helper_bounds_memory_and_ignores_filename(live_image_storage):
    storage, prefix = live_image_storage
    upload = UploadFile(filename="untrusted-name.txt", file=BytesIO(b"\x89PNGimage"))
    content = asyncio.run(read_image_upload(upload))
    url = ImageUploadService(storage).upload(
        prefix + "events/covers", content, "text/plain"
    )
    assert upload.filename not in url
    upload.read = AsyncMock(return_value=b"x" * 11)
    with pytest.raises(ImageTooLargeError):
        asyncio.run(read_image_upload(upload, max_size_bytes=10))
    upload.read.assert_awaited_once_with(11)


def test_read_helper_accepts_exact_limit():
    upload = UploadFile(file=BytesIO(b"x" * 10))
    assert asyncio.run(read_image_upload(upload, max_size_bytes=10)) == b"x" * 10


@pytest.fixture
def s3_storage(monkeypatch):
    monkeypatch.setattr(
        module,
        "settings",
        replace(
            module.settings,
            aws_s3_bucket="hangy-test-images",
            aws_region="us-east-1",
        ),
    )

    def unit_client(region):
        return boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        )

    monkeypatch.setattr(module, "_create_s3_client", unit_client)
    return S3ImageStorage()


def test_s3_upload_and_idempotent_delete(live_image_storage):
    storage, prefix = live_image_storage
    key = prefix + "events/covers/image.png"
    url = storage.upload(key, b"\x89PNG", "image/png")
    assert url == f"{storage.public_base_url}/{key}"
    assert stored_images(storage, prefix) == {url: (b"\x89PNG", "image/png")}
    storage.delete(url)
    storage.delete(url)
    assert stored_images(storage, prefix) == {}


@pytest.mark.parametrize(
    "url",
    [
        BASE,
        BASE + "-other/image.png",
        BASE + "/../outside.png",
        BASE + "/%2e%2e/outside.png",
        BASE + "/image.png?query=1",
        BASE + "/image.png#fragment",
        "https://images.hangy.test.evil/media/image.png",
        "https://images.hangy.test@evil/media/image.png",
        "http://images.hangy.test/media/image.png",
        "https://external.test/image.png",
        "https://[broken",
    ],
)
def test_ownership_rejects_external_or_ambiguous_urls(s3_storage, url):
    assert not s3_storage.owns(url)
    # A foreign URL must not cause any SDK construction or deletion.
    s3_storage.delete(url)
    assert s3_storage._client is None


def test_owned_url_and_encoded_key(s3_storage):
    url = BASE + "/experiences/123/photo%20name.png"
    assert s3_storage.owns(url)
    with Stubber(s3_storage._get_client()) as stub:
        stub.add_response(
            "delete_object",
            {},
            {"Bucket": "hangy-test-images", "Key": "experiences/123/photo name.png"},
        )
        s3_storage.delete(url)
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("operation", ["upload", "delete"])
def test_s3_errors_become_domain_errors(s3_storage, operation):
    with Stubber(s3_storage._get_client()) as stub:
        stub.add_client_error(
            "put_object" if operation == "upload" else "delete_object",
            "AccessDenied",
            http_status_code=403,
        )
        with pytest.raises(
            ImageStorageUnavailableError, match="Image storage unavailable"
        ):
            if operation == "upload":
                ImageUploadService(s3_storage).upload("events/covers", b"\x89PNG", "x")
            else:
                s3_storage.delete(BASE + "/image.png")
        stub.assert_no_pending_responses()


def test_delete_missing_object_error_is_success(s3_storage):
    with Stubber(s3_storage._get_client()) as stub:
        stub.add_client_error("delete_object", "NoSuchKey", http_status_code=404)
        s3_storage.delete(BASE + "/missing.png")
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("operation", ["upload", "delete"])
@pytest.mark.parametrize(
    "error",
    [NoCredentialsError(), EndpointConnectionError(endpoint_url="https://s3.test")],
)
def test_client_creation_and_connection_failures(
    s3_storage, monkeypatch, operation, error
):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(module.boto3, "client", fail)
    with pytest.raises(ImageStorageUnavailableError) as caught:
        if operation == "upload":
            s3_storage.upload("image.png", b"\x89PNG", "image/png")
        else:
            s3_storage.delete(BASE + "/image.png")
    assert caught.value.__cause__ is error


def test_unconfigured_storage_is_lazy_and_unavailable(monkeypatch):
    monkeypatch.setattr(module, "settings", replace(module.settings, aws_s3_bucket=""))
    monkeypatch.setattr(
        module.boto3, "client", lambda *a, **kw: pytest.fail("Must not contact AWS")
    )
    storage = get_image_storage()
    assert not storage.owns(BASE + "/image.png")
    with pytest.raises(ImageStorageUnavailableError):
        ImageUploadService(storage).upload("events/covers", b"\x89PNG", "image/png")


def test_dependency_uses_fake(image_storage):
    from app.main import app

    assert app.dependency_overrides[get_image_storage]() is image_storage


@pytest.mark.parametrize("bucket", ["", "   ", " images-test "])
@pytest.mark.parametrize("region", [" us-east-2 ", " eu-west-1 "])
def test_configuration_trims_values_and_derives_public_url(monkeypatch, bucket, region):
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    monkeypatch.setenv("AWS_S3_BUCKET", bucket)
    monkeypatch.setenv("AWS_REGION", region)
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "https://ignored.test/media")
    monkeypatch.setenv("IMAGE_MAX_SIZE_BYTES", "1024")
    configured = runpy.run_path("app/config.py")["settings"]
    assert configured.aws_s3_bucket == bucket.strip()
    assert configured.image_max_size_bytes == 1024
    expected = (
        f"https://{bucket.strip()}.s3.{region.strip()}.amazonaws.com"
        if bucket.strip()
        else ""
    )
    assert configured.s3_public_base_url == expected


def test_image_configuration_defaults(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    for name in (
        "AWS_S3_BUCKET",
        "AWS_REGION",
        "IMAGE_MAX_SIZE_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    configured = runpy.run_path("app/config.py")["settings"]
    assert configured.aws_s3_bucket == ""
    assert configured.aws_region == "us-east-1"
    assert configured.s3_public_base_url == ""
    assert configured.image_max_size_bytes == LIMIT
