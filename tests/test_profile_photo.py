from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.services import ImageStorageUnavailableError
from app.infrastructure.repository.models import UserModel
from tests import test_delete_experience_photo
from tests.test_delete_experience_photo import ANA_ID, _authorization

PATH = "/users/me/photo"
JPG = b"\xff\xd8\xffimage"
PNG = b"\x89PNGimage"
SessionFactory = sessionmaker[Session]


@pytest.fixture
def client() -> Iterator[tuple[TestClient, SessionFactory]]:
    yield from test_delete_experience_photo.client.__wrapped__()


def _upload(test_client: TestClient, content: bytes = JPG, *, auth: bool = True):
    return test_client.post(
        PATH,
        files={"file": ("foto.txt", content, "text/plain")},
        headers=_authorization(ANA_ID) if auth else {},
    )


def _stored_url(session: SessionFactory) -> str | None:
    with session() as db:
        return db.scalar(
            select(UserModel.profile_photo_url).where(UserModel.user_id == ANA_ID)
        )


@pytest.mark.parametrize(("content", "extension"), [(JPG, "jpg"), (PNG, "png")])
def test_upload_sets_profile_photo(client, image_storage, content, extension) -> None:
    test_client, session = client

    response = _upload(test_client, content)

    assert response.status_code == 200
    url = response.json()["photo_url"]
    assert url.startswith(f"{image_storage.base_url}/profile-photos/{ANA_ID}/")
    assert url.endswith(f".{extension}")
    assert _stored_url(session) == url
    assert set(image_storage.objects) == {url}


def test_new_photo_replaces_and_deletes_previous(client, image_storage) -> None:
    test_client, session = client
    first = _upload(test_client).json()["photo_url"]

    second = _upload(test_client, PNG).json()["photo_url"]

    assert second != first
    assert _stored_url(session) == second
    assert set(image_storage.objects) == {second}


def test_requires_token(client, image_storage) -> None:
    test_client, session = client

    response = _upload(test_client, auth=False)

    assert response.status_code == 401
    assert image_storage.objects == {}
    assert _stored_url(session) is None


def test_invalid_image_returns_415_and_keeps_photo(client, image_storage) -> None:
    test_client, session = client

    response = _upload(test_client, b"GIF89a")

    assert response.status_code == 415
    assert image_storage.objects == {}
    assert _stored_url(session) is None


def test_storage_failure_returns_503(client, image_storage, monkeypatch) -> None:
    test_client, session = client

    def fail(*args, **kwargs):
        raise ImageStorageUnavailableError

    monkeypatch.setattr(image_storage, "upload", fail)

    response = _upload(test_client)

    assert response.status_code == 503
    assert _stored_url(session) is None
