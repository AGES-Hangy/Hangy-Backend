from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.domain.enums import EventParticipantStatusEnum
from app.domain.services import ImageStorageUnavailableError
from app.infrastructure.repository.experience import SqlAlchemyExperienceRepository
from app.infrastructure.repository.models import (
    EventExperienceModel,
    EventParticipantModel,
    ExperienceImagesModel,
)
from tests import test_delete_experience_photo
from tests.test_delete_experience_photo import (
    ANA_ID,
    BRUNO_ID,
    EVENT_ID,
    NOW,
    OUTSIDER_ID,
    _authorization,
    _event,
    _experience,
    _photo,
)

JPG = b"\xff\xd8\xffimage"
PNG = b"\x89PNGimage"
LIMIT_BYTES = 5 * 1024 * 1024
SessionFactory = sessionmaker[Session]


@pytest.fixture
def client() -> Iterator[tuple[TestClient, SessionFactory]]:
    yield from test_delete_experience_photo.client.__wrapped__()


def _create_experience(
    session: SessionFactory,
    user_id: UUID = ANA_ID,
    *,
    status: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> UUID:
    with session() as db:
        participant = EventParticipantModel(
            user_id=user_id, event_id=EVENT_ID, status=status
        )
        db.add(participant)
        db.flush()
        experience = EventExperienceModel(
            experience_id=uuid4(),
            event_participant_id=participant.participant_id,
            description="Foi demais",
        )
        db.add(experience)
        db.commit()
        return experience.experience_id


def _upload(
    test_client: TestClient,
    experience_id: UUID | str,
    user_id: UUID | None = ANA_ID,
    *,
    content: bytes = JPG,
    filename: str = "foto.jpg",
    mime: str = "image/jpeg",
):
    headers = _authorization(user_id) if user_id is not None else {}
    return test_client.post(
        f"/experiences/{experience_id}/images",
        files={"file": (filename, content, mime)},
        headers=headers,
    )


def _image_rows(session: SessionFactory) -> list[ExperienceImagesModel]:
    with session() as db:
        return list(db.scalars(select(ExperienceImagesModel)))


@pytest.mark.parametrize(
    ("content", "mime", "extension"),
    [(JPG, "image/jpeg", "jpg"), (PNG, "image/png", "png")],
)
def test_owner_uploads_photo_and_gets_bucket_url(
    client, image_storage, content, mime, extension
) -> None:
    test_client, session = client
    experience_id = _create_experience(session)

    response = _upload(
        test_client, experience_id, content=content, filename="x.txt", mime="text/plain"
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"photo_id", "photo_url", "created_at"}
    url = body["photo_url"]
    assert url.startswith(f"{image_storage.base_url}/experiences/{experience_id}/")
    assert url.endswith(f".{extension}")
    assert image_storage.objects == {url: (content, mime)}

    rows = _image_rows(session)
    assert len(rows) == 1
    assert rows[0].photo_id == UUID(body["photo_id"])
    assert rows[0].experience_id == experience_id
    assert rows[0].photo_url == url
    assert rows[0].deleted_at is None


def test_uploaded_photo_appears_in_event_gallery(client, image_storage) -> None:
    test_client, session = client
    experience_id = _create_experience(session)

    url = _upload(test_client, experience_id).json()["photo_url"]
    gallery = test_client.get(
        f"/events/{EVENT_ID}/photos", headers=_authorization(OUTSIDER_ID)
    )

    assert gallery.status_code == 200
    assert [item["photo_url"] for item in gallery.json()["items"]] == [url]
    assert gallery.json()["items"][0]["author"]["id"] == str(ANA_ID)


def test_missing_token_returns_401_and_stores_nothing(client, image_storage) -> None:
    test_client, session = client
    experience_id = _create_experience(session)

    response = _upload(test_client, experience_id, user_id=None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert image_storage.objects == {}
    assert _image_rows(session) == []


@pytest.mark.parametrize("case", ["missing", "other_user", "deleted", "deleted_event"])
def test_unavailable_experience_returns_404_and_stores_nothing(
    client, image_storage, case
) -> None:
    test_client, session = client
    experience_id: UUID = uuid4()
    uploader = ANA_ID
    if case == "other_user":
        experience_id = _create_experience(session, BRUNO_ID)
    elif case == "deleted":
        with session() as db:
            experience_id = _experience(db, ANA_ID, deleted_at=NOW).experience_id
            db.commit()
    elif case == "deleted_event":
        deleted_event = _event(uuid4(), "Evento removido", deleted_at=NOW)
        with session() as db:
            db.add(deleted_event)
            db.flush()
            experience_id = _experience(
                db, ANA_ID, deleted_event.event_id
            ).experience_id
            db.commit()

    response = _upload(test_client, experience_id, uploader)

    assert response.status_code == 404
    assert response.json() == {"detail": "Experience not found"}
    assert image_storage.objects == {}
    assert _image_rows(session) == []


@pytest.mark.parametrize(
    "status",
    [
        EventParticipantStatusEnum.CANCELLED,
        EventParticipantStatusEnum.REMOVED,
        EventParticipantStatusEnum.PENDING,
    ],
)
def test_participant_no_longer_confirmed_returns_403(
    client, image_storage, status
) -> None:
    test_client, session = client
    experience_id = _create_experience(session, status=status)

    response = _upload(test_client, experience_id)

    assert response.status_code == 403
    assert response.json() == {"detail": "Only confirmed participants can post"}
    assert image_storage.objects == {}
    assert _image_rows(session) == []


def _seed_photos(
    session: SessionFactory, experience_id: UUID, active: int, deleted: int = 0
) -> None:
    with session() as db:
        experience = db.get(EventExperienceModel, experience_id)
        for index in range(active + deleted):
            image = _photo(
                db,
                experience,
                f"https://images.hangy.test/experiences/{experience_id}/{index}.jpg",
                created_at=NOW - timedelta(minutes=index),
            )
            if index >= active:
                image.deleted_at = NOW
        db.commit()


def test_photo_limit_reached_returns_409_and_stores_nothing(
    client, image_storage
) -> None:
    test_client, session = client
    experience_id = _create_experience(session)
    _seed_photos(session, experience_id, settings.experience_photo_limit)

    response = _upload(test_client, experience_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Photo limit reached"}
    assert image_storage.objects == {}
    assert len(_image_rows(session)) == settings.experience_photo_limit


def test_last_photo_below_limit_is_accepted_and_deleted_photos_do_not_count(
    client, image_storage
) -> None:
    test_client, session = client
    experience_id = _create_experience(session)
    _seed_photos(session, experience_id, settings.experience_photo_limit - 1, deleted=3)

    first = _upload(test_client, experience_id)
    second = _upload(test_client, experience_id)

    assert first.status_code == 201
    assert second.status_code == 409
    assert list(image_storage.objects) == [first.json()["photo_url"]]


def test_limit_is_per_user(client, image_storage) -> None:
    test_client, session = client
    ana_experience = _create_experience(session, ANA_ID)
    bruno_experience = _create_experience(session, BRUNO_ID)
    _seed_photos(session, ana_experience, settings.experience_photo_limit)

    response = _upload(test_client, bruno_experience, BRUNO_ID)

    assert response.status_code == 201


@pytest.mark.parametrize("extra_byte", [False, True])
def test_size_boundary(client, image_storage, extra_byte) -> None:
    test_client, session = client
    experience_id = _create_experience(session)
    content = b"\xff\xd8\xff" + bytes(LIMIT_BYTES - 3 + extra_byte)

    response = _upload(test_client, experience_id, content=content)

    if extra_byte:
        assert response.status_code == 413
        assert response.json() == {"detail": "Image too large"}
        assert image_storage.objects == {}
        assert _image_rows(session) == []
    else:
        assert response.status_code == 201


@pytest.mark.parametrize("content", [b"", b"GIF89a", b"not an image"])
def test_unsupported_content_returns_415(client, image_storage, content) -> None:
    test_client, session = client
    experience_id = _create_experience(session)

    response = _upload(
        test_client, experience_id, content=content, filename="a.jpg", mime="image/jpeg"
    )

    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported image type"}
    assert image_storage.objects == {}
    assert _image_rows(session) == []


def test_missing_file_field_returns_422(client, image_storage) -> None:
    test_client, session = client
    experience_id = _create_experience(session)

    response = test_client.post(
        f"/experiences/{experience_id}/images",
        data={"photo_url": "https://images.hangy.test/x.jpg"},
        headers=_authorization(ANA_ID),
    )

    assert response.status_code == 422
    assert image_storage.objects == {}
    assert _image_rows(session) == []


def test_storage_unavailable_returns_503_and_creates_no_row(
    client, image_storage, monkeypatch
) -> None:
    test_client, session = client
    experience_id = _create_experience(session)

    def fail_upload(key, content, content_type):
        raise ImageStorageUnavailableError("down")

    monkeypatch.setattr(image_storage, "upload", fail_upload)

    response = _upload(test_client, experience_id)

    assert response.status_code == 503
    assert response.json() == {"detail": "Image storage unavailable"}
    assert _image_rows(session) == []


def test_insert_failure_deletes_uploaded_object(
    client, image_storage, monkeypatch
) -> None:
    test_client, session = client
    experience_id = _create_experience(session)

    def fail_insert(self, experience_id, photo_url):
        assert photo_url in image_storage.objects
        raise RuntimeError("insert failed")

    monkeypatch.setattr(SqlAlchemyExperienceRepository, "add_photo", fail_insert)

    with pytest.raises(RuntimeError, match="insert failed"):
        _upload(test_client, experience_id)

    assert image_storage.objects == {}
    assert _image_rows(session) == []


def test_orphan_cleanup_failure_is_logged_and_keeps_original_error(
    client, image_storage, monkeypatch, caplog
) -> None:
    test_client, session = client
    experience_id = _create_experience(session)

    def fail_insert(self, experience_id, photo_url):
        raise RuntimeError("insert failed")

    def fail_delete(url):
        raise ImageStorageUnavailableError("down")

    monkeypatch.setattr(SqlAlchemyExperienceRepository, "add_photo", fail_insert)
    monkeypatch.setattr(image_storage, "delete", fail_delete)

    with (
        caplog.at_level(logging.ERROR, logger="app.domain.services.experience"),
        pytest.raises(RuntimeError, match="insert failed"),
    ):
        _upload(test_client, experience_id)

    assert "Failed to delete orphan S3 object" in caplog.text
