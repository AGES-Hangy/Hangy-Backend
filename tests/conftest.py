import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("LOCATION_OBFUSCATION_SECRET", "test-location-secret")
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"


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
def isolate_image_storage(monkeypatch, image_storage):
    from botocore.httpsession import URLLib3Session

    from app.infrastructure.storage import get_image_storage
    from app.main import app

    monkeypatch.setitem(
        app.dependency_overrides, get_image_storage, lambda: image_storage
    )

    def deny_aws_network(*args, **kwargs):
        pytest.fail("Tests must use an image storage fake, Stubber, or moto, not AWS")

    monkeypatch.setattr(URLLib3Session, "send", deny_aws_network)
