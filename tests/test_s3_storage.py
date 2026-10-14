import runpy
from dataclasses import replace
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import pytest
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.stub import Stubber
from moto import mock_aws

from app.infrastructure.storage import S3Storage, StorageError, StorageNotFoundError
from app.infrastructure.storage import s3_storage as module

BUCKET = "hangy-test-storage"


@pytest.fixture
def storage(monkeypatch):
    monkeypatch.setattr(
        module,
        "settings",
        replace(module.settings, s3_bucket_name=BUCKET, aws_region="us-east-2"),
    )
    with mock_aws():
        adapter = S3Storage()
        adapter._client.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "us-east-2"},
        )
        yield adapter


def test_upload_download_delete_and_missing_object(storage):
    storage.upload_file("users/a/photo", BytesIO(b"photo"), content_type="image/png")
    metadata = storage._client.head_object(Bucket=BUCKET, Key="users/a/photo")
    assert metadata["ContentType"] == "image/png"
    output = BytesIO()
    storage.download_file("users/a/photo", output)
    assert output.getvalue() == b"photo"
    storage.delete_file("users/a/photo")
    storage.delete_file("users/a/photo")
    with pytest.raises(StorageNotFoundError):
        storage.download_file("users/a/photo", BytesIO())


def test_multipart_upload(storage):
    content = b"x" * (9 * 1024 * 1024)
    storage.upload_file("large", BytesIO(content))
    output = BytesIO()
    storage.download_file("large", output)
    assert output.getvalue() == content


def test_list_is_paginated_and_filters_prefix_without_caching(storage):
    for key in ("users/a/1", "users/a/2", "users/b/1"):
        storage.upload_file(key, BytesIO(b"data"))
    first = storage.list_files(prefix="users/a/", limit=1)
    assert first.keys == ("users/a/1",)
    assert first.next_token
    second = storage.list_files(
        prefix="users/a/", limit=1, continuation_token=first.next_token
    )
    assert second.keys == ("users/a/2",)
    assert second.next_token is None
    storage.delete_file("users/a/1")
    assert storage.list_files(prefix="users/a/").keys == ("users/a/2",)
    assert storage.list_files(prefix="missing/").keys == ()


def test_signed_url_uses_sigv4_bucket_region_and_expiration(storage):
    url = urlparse(storage.generate_download_url("users/a/photo name", expires_in=60))
    query = parse_qs(url.query)
    assert url.scheme == "https"
    assert url.hostname == f"{BUCKET}.s3.amazonaws.com"
    assert url.path == "/users/a/photo%20name"
    assert query["X-Amz-Expires"] == ["60"]
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert "/us-east-2/s3/aws4_request" in query["X-Amz-Credential"][0]


@pytest.mark.parametrize("key", ["", "a" * 1025, "é" * 513])
def test_invalid_key_rejected_before_s3(storage, key):
    with Stubber(storage._client):
        for call in (
            lambda: storage.upload_file(key, BytesIO()),
            lambda: storage.download_file(key, BytesIO()),
            lambda: storage.delete_file(key),
            lambda: storage.generate_download_url(key),
        ):
            with pytest.raises(ValueError, match="Object key"):
                call()


@pytest.mark.parametrize("expires_in", [0, -1, 604801])
def test_invalid_expiration(storage, expires_in):
    with pytest.raises(ValueError, match="URL lifetime"):
        storage.generate_download_url("photo", expires_in=expires_in)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 1001},
        {"prefix": "é" * 513},
        {"continuation_token": ""},
        {"continuation_token": "x" * 8193},
    ],
)
def test_invalid_listing_rejected_before_s3(storage, kwargs):
    with Stubber(storage._client), pytest.raises(ValueError):
        storage.list_files(**{"prefix": "users/", **kwargs})


def test_access_denied_is_not_reported_as_missing(storage):
    with Stubber(storage._client) as stub:
        stub.add_client_error("head_object", "AccessDenied", http_status_code=403)
        with pytest.raises(StorageError) as error:
            storage.download_file("private", BytesIO())
        assert not isinstance(error.value, StorageNotFoundError)
        assert isinstance(error.value.__cause__, ClientError)
        stub.assert_no_pending_responses()


def test_credentials_failure_is_wrapped(storage, monkeypatch):
    def fail(*args, **kwargs):
        raise NoCredentialsError()

    monkeypatch.setattr(storage._client, "generate_presigned_url", fail)
    with pytest.raises(StorageError) as error:
        storage.generate_download_url("photo")
    assert isinstance(error.value.__cause__, NoCredentialsError)


@pytest.mark.parametrize("field", ["s3_bucket_name", "aws_region"])
def test_missing_configuration_fails_before_client_creation(monkeypatch, field):
    monkeypatch.setattr(module, "settings", replace(module.settings, **{field: ""}))

    def unexpected_client(*args, **kwargs):
        pytest.fail("Must validate configuration before contacting AWS")

    monkeypatch.setattr(module, "_create_s3_client", unexpected_client)
    with pytest.raises(StorageError, match="Configure"):
        S3Storage()


@pytest.mark.parametrize("value", ["", "   ", " us-east-2 "])
def test_environment_values_are_trimmed(monkeypatch, value):
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    monkeypatch.setenv("AWS_REGION", value)
    monkeypatch.setenv("S3_BUCKET_NAME", " hangy-test-storage ")
    configured = runpy.run_path("app/config.py")["settings"]
    assert configured.aws_region == value.strip()
    assert configured.s3_bucket_name == BUCKET
