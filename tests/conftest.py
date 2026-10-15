import os
from uuid import uuid4

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("LOCATION_OBFUSCATION_SECRET", "test-location-secret")


class FakeImageStorage:
    def __init__(self):
        self.base_url = "https://images.hangy.test"
        self.objects = {}

    def upload(self, key, content, content_type):
        url = f"{self.base_url}/{key}"
        self.objects[url] = (content, content_type)
        return url

    def delete(self, url):
        self.objects.pop(url, None)

    def owns(self, url):
        return url.startswith(self.base_url + "/")


@pytest.fixture
def image_storage():
    return FakeImageStorage()


@pytest.fixture(autouse=True)
def isolate_image_storage(monkeypatch, image_storage, request):
    from botocore.httpsession import URLLib3Session

    from app.infrastructure.storage import get_image_storage
    from app.main import app

    monkeypatch.setitem(
        app.dependency_overrides, get_image_storage, lambda: image_storage
    )

    def deny_aws_network(*args, **kwargs):
        pytest.fail("Tests must use an image storage fake, Stubber, or moto, not AWS")

    if "live_s3" not in request.fixturenames:
        monkeypatch.setattr(URLLib3Session, "send", deny_aws_network)


@pytest.fixture
def live_s3():
    """Use .env/SDK credentials; delete only this test's unique object prefix."""
    from app.config import settings
    from app.infrastructure.storage.s3 import _create_s3_client

    client = None
    prefix = f"tests/{uuid4().hex}/"
    buckets = set()

    def register(bucket):
        nonlocal client
        if not bucket:
            pytest.skip("Set S3_BUCKET_NAME / AWS_S3_BUCKET in the environment or .env")
        if client is None:
            client = _create_s3_client(settings.aws_region)
        buckets.add(bucket)
        return prefix

    try:
        yield register
    finally:
        for bucket in buckets:
            pages = client.get_paginator("list_objects_v2").paginate(
                Bucket=bucket, Prefix=prefix
            )
            for page in pages:
                for obj in page.get("Contents", []):
                    client.delete_object(Bucket=bucket, Key=obj["Key"])
        if client is not None:
            client.close()


@pytest.fixture
def live_storage(live_s3):
    from app.config import settings
    from app.infrastructure.storage import S3Storage

    register = live_s3
    prefix = register(settings.s3_bucket_name)
    storage = S3Storage()
    try:
        yield storage, prefix
    finally:
        storage._client.close()


@pytest.fixture
def live_image_storage(live_s3):
    from app.config import settings
    from app.infrastructure.storage import S3ImageStorage

    register = live_s3
    prefix = register(settings.aws_s3_bucket)
    storage = S3ImageStorage()
    try:
        yield storage, prefix
    finally:
        if storage._client is not None:
            storage._client.close()
