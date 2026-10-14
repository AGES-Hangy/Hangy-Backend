import asyncio
import runpy
from dataclasses import replace
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import UUID

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
BASE = "https://images.hangy.test/media"


@pytest.mark.parametrize(
    ("content", "header", "extension", "mime", "folder"),
    [
        (b"\xff\xd8\xffimage", "image/png", "jpg", "image/jpeg", "events/covers"),
        (b"\x89PNGimage", "text/plain", "png", "image/png", "experiences/123"),
    ],
)
def test_upload_detects_content_and_generates_uuid_key(
    image_storage, content, header, extension, mime, folder
):
    service = ImageUploadService(image_storage)
    url = service.upload(folder, content, header)
    assert url.startswith(f"{image_storage.base_url}/{folder}/")
    name = url.rsplit("/", 1)[1]
    assert name.endswith("." + extension)
    assert UUID(name.split(".")[0]).version == 4
    assert image_storage.objects == {url: (content, mime)}
    assert service.owns(url)
    assert not service.owns("https://external.test/photo.png")
    service.delete(url)
    service.delete(url)
    assert image_storage.objects == {}


@pytest.mark.parametrize("content", [b"", b"text renamed to .png", b"GIF89a"])
def test_invalid_content_does_not_write(image_storage, content):
    with pytest.raises(UnsupportedImageTypeError, match="Unsupported image type"):
        ImageUploadService(image_storage).upload("events/covers", content, "image/png")
    assert image_storage.objects == {}


def test_size_boundary_and_no_write_above_limit(image_storage):
    service = ImageUploadService(image_storage)
    content = b"\x89PNG" + bytes(LIMIT - 4)
    url = service.upload("events/covers", content, "image/png")
    assert image_storage.objects[url] == (content, "image/png")
    with pytest.raises(ImageTooLargeError, match="Image too large"):
        service.upload("events/covers", content + b"x", "image/png")
    assert len(image_storage.objects) == 1


def test_read_helper_bounds_memory_and_ignores_filename(image_storage):
    upload = UploadFile(filename="untrusted-name.txt", file=BytesIO(b"\x89PNGimage"))
    content = asyncio.run(read_image_upload(upload))
    url = ImageUploadService(image_storage).upload(
        "events/covers", content, "text/plain"
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
            s3_public_base_url=BASE + "/",
            aws_region="us-east-1",
        ),
    )
    return S3ImageStorage()


def test_s3_upload_and_idempotent_delete(s3_storage):
    with Stubber(s3_storage._get_client()) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "hangy-test-images",
                "Key": "events/covers/image.png",
                "Body": b"\x89PNG",
                "ContentType": "image/png",
            },
        )
        url = s3_storage.upload("events/covers/image.png", b"\x89PNG", "image/png")
        assert url == BASE + "/events/covers/image.png"
        params = {"Bucket": "hangy-test-images", "Key": "events/covers/image.png"}
        stub.add_response("delete_object", {}, params)
        stub.add_response("delete_object", {}, params)
        s3_storage.delete(url)
        s3_storage.delete(url)
        stub.assert_no_pending_responses()


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
@pytest.mark.parametrize("public_base", ["", "   ", " https://cdn.test/media/ "])
def test_configuration_trims_values_and_derives_public_url(
    monkeypatch, bucket, public_base
):
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    monkeypatch.setenv("AWS_S3_BUCKET", bucket)
    monkeypatch.setenv("AWS_REGION", " us-east-2 ")
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", public_base)
    monkeypatch.setenv("IMAGE_MAX_SIZE_BYTES", "1024")
    configured = runpy.run_path("app/config.py")["settings"]
    assert configured.aws_s3_bucket == bucket.strip()
    assert configured.image_max_size_bytes == 1024
    expected = public_base.strip().rstrip("/") or (
        f"https://{bucket.strip()}.s3.us-east-2.amazonaws.com" if bucket.strip() else ""
    )
    assert configured.s3_public_base_url == expected


def test_image_configuration_defaults(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    for name in (
        "AWS_S3_BUCKET",
        "AWS_REGION",
        "S3_PUBLIC_BASE_URL",
        "IMAGE_MAX_SIZE_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)
    configured = runpy.run_path("app/config.py")["settings"]
    assert configured.aws_s3_bucket == ""
    assert configured.aws_region == "us-east-1"
    assert configured.s3_public_base_url == ""
    assert configured.image_max_size_bytes == LIMIT
