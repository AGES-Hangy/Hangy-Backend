from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.domain.services import ImageStorageUnavailableError
from app.infrastructure.repository.models import EventModel, user_tag
from tests import test_create_event
from tests.test_create_event import FOOTBALL_ID, ORGANIZER_ID, auth_header, payload

PATH = "/uploads/event-covers"
LIMIT = 5 * 1024 * 1024


@pytest.fixture
def client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    yield from test_create_event.client.__wrapped__()


@pytest.mark.parametrize(
    ("content", "mime", "extension"),
    [
        (b"\xff\xd8\xffimage", "image/jpeg", "jpg"),
        (b"\x89PNGimage", "image/png", "png"),
    ],
)
def test_upload_returns_bucket_url_and_stores_detected_type(
    client, image_storage, content, mime, extension
) -> None:
    test_client, _ = client
    response = test_client.post(
        PATH,
        files={"file": ("untrusted.txt", content, "text/plain")},
        headers=auth_header(),
    )

    assert response.status_code == 201
    assert set(response.json()) == {"cover_photo_url"}
    url = response.json()["cover_photo_url"]
    assert url.startswith(f"{image_storage.base_url}/events/covers/")
    name = url.rsplit("/", 1)[1]
    assert name.endswith(f".{extension}")
    assert UUID(name.split(".")[0]).version == 4
    assert image_storage.objects == {url: (content, mime)}


@pytest.mark.parametrize("authentication", ["missing", "invalid", "expired"])
def test_upload_requires_valid_token(client, image_storage, authentication) -> None:
    test_client, _ = client
    headers = {}
    if authentication == "invalid":
        headers = {"Authorization": "Bearer invalid"}
    elif authentication == "expired":
        token = jwt.encode(
            {"sub": str(ORGANIZER_ID), "exp": datetime.now(UTC) - timedelta(minutes=1)},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        headers = {"Authorization": f"Bearer {token}"}

    response = test_client.post(
        PATH,
        files={"file": ("cover.png", b"\x89PNGimage", "image/png")},
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert image_storage.objects == {}


@pytest.mark.parametrize("extra_byte", [False, True])
def test_upload_size_boundary(client, image_storage, extra_byte) -> None:
    test_client, _ = client
    content = b"\x89PNG" + bytes(LIMIT - 4 + extra_byte)

    response = test_client.post(
        PATH, files={"file": ("cover.png", content, "image/png")}, headers=auth_header()
    )

    if extra_byte:
        assert response.status_code == 413
        assert response.json() == {"detail": "Image too large"}
        assert image_storage.objects == {}
    else:
        assert response.status_code == 201
        assert image_storage.objects[response.json()["cover_photo_url"]][0] == content


@pytest.mark.parametrize("content", [b"", b"not an image", b"GIF89a"])
def test_invalid_image_returns_415_without_writing(client, image_storage, content):
    test_client, _ = client
    response = test_client.post(
        PATH, files={"file": ("fake.png", content, "image/png")}, headers=auth_header()
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported image type"}
    assert image_storage.objects == {}


def test_missing_file_returns_422(client, image_storage) -> None:
    test_client, _ = client
    response = test_client.post(PATH, headers=auth_header())

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "file"]
    assert image_storage.objects == {}


def test_storage_failure_returns_503(client, image_storage, monkeypatch) -> None:
    test_client, _ = client
    monkeypatch.setattr(
        image_storage, "upload", Mock(side_effect=ImageStorageUnavailableError)
    )

    response = test_client.post(
        PATH,
        files={"file": ("cover.png", b"\x89PNGimage", "image/png")},
        headers=auth_header(),
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Image storage unavailable"}
    assert image_storage.objects == {}


def test_uploaded_cover_is_saved_and_visible_in_detail_and_feed(client) -> None:
    test_client, session_factory = client
    upload = test_client.post(
        PATH,
        files={"file": ("cover.png", b"\x89PNGimage", "image/png")},
        headers=auth_header(),
    )
    assert upload.status_code == 201
    url = upload.json()["cover_photo_url"]

    created = test_client.post(
        "/events", json=payload(cover_photo_url=url), headers=auth_header()
    )
    assert created.status_code == 201
    event_id = created.json()["event_id"]
    with session_factory() as db:
        assert db.get(EventModel, UUID(event_id)).cover_photo_url == url
        db.execute(user_tag.insert().values(user_id=ORGANIZER_ID, tag_id=FOOTBALL_ID))
        db.commit()

    detail = test_client.get(f"/events/{event_id}", headers=auth_header())
    assert detail.status_code == 200
    assert detail.json()["cover_photo_url"] == url
    feed = test_client.get("/feed", headers=auth_header())
    assert feed.status_code == 200
    items = [item for section in feed.json()["sections"] for item in section["items"]]
    assert any(
        item["event_id"] == event_id and item["cover_photo_url"] == url
        for item in items
    )


def test_openapi_documents_multipart_and_all_upload_responses(client) -> None:
    test_client, _ = client
    schema = test_client.get("/openapi.json").json()
    operation = schema["paths"][PATH]["post"]

    assert set(operation["responses"]) >= {"201", "401", "413", "415", "422", "503"}
    assert operation["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EventCoverUploadOutput"
    }
    assert operation["security"]
    body = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    body_schema = schema["components"]["schemas"][body["$ref"].split("/")[-1]]
    assert body_schema["required"] == ["file"]
    assert (
        body_schema["properties"]["file"]["contentMediaType"]
        == "application/octet-stream"
    )
