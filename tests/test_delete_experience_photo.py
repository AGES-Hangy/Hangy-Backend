from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.experience import SqlAlchemyExperienceRepository
from app.infrastructure.repository.models import (
    EventExperienceModel,
    EventModel,
    EventParticipantModel,
    ExperienceImagesModel,
    UserModel,
)
from app.main import app

ORGANIZER_ID = UUID("a2260000-0000-4000-8000-000000000001")
ANA_ID = UUID("a2260000-0000-4000-8000-000000000002")
BRUNO_ID = UUID("a2260000-0000-4000-8000-000000000003")
OUTSIDER_ID = UUID("a2260000-0000-4000-8000-000000000004")
EVENT_ID = UUID("a2260000-0000-4000-8000-000000000005")
NOW = datetime.now(UTC)

FORBIDDEN_DETAIL = "Only the author or the organizer can delete"
SessionFactory = sessionmaker[Session]


@pytest.fixture
def client() -> Iterator[tuple[TestClient, SessionFactory]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        for user_id, name in (
            (ORGANIZER_ID, "Organizador"),
            (ANA_ID, "Ana Souza"),
            (BRUNO_ID, "Bruno Lima"),
            (OUTSIDER_ID, "Terceiro"),
        ):
            db.add(
                UserModel(
                    user_id=user_id,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email=f"{user_id}@hangy.test",
                    password_hash="hash",
                    name=name,
                )
            )
        db.add(_event(EVENT_ID, "Pelada encerrada"))
        db.commit()

    def override_get_db() -> Iterator[Session]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _event(
    event_id: UUID,
    title: str,
    *,
    deleted_at: datetime | None = None,
) -> EventModel:
    return EventModel(
        event_id=event_id,
        event_creator_id=ORGANIZER_ID,
        event_title=title,
        event_latitude=0.0,
        event_longitude=0.0,
        starts_at=NOW - timedelta(days=2),
        ends_at=NOW - timedelta(days=2) + timedelta(hours=2),
        event_status=EventStatusEnum.FINISHED,
        event_privacy=EventPrivacyEnum.PUBLIC,
        deleted_at=deleted_at,
    )


def _authorization(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": NOW + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _experience(
    db: Session,
    user_id: UUID,
    event_id: UUID = EVENT_ID,
    *,
    deleted_at: datetime | None = None,
) -> EventExperienceModel:
    participant = EventParticipantModel(
        user_id=user_id,
        event_id=event_id,
        status=EventParticipantStatusEnum.CONFIRMED,
    )
    db.add(participant)
    db.flush()
    experience = EventExperienceModel(
        experience_id=uuid4(),
        event_participant_id=participant.participant_id,
        description="Foi demais",
        deleted_at=deleted_at,
    )
    db.add(experience)
    db.flush()
    return experience


def _photo(
    db: Session,
    experience: EventExperienceModel,
    url: str,
    *,
    created_at: datetime = NOW,
) -> ExperienceImagesModel:
    image = ExperienceImagesModel(
        photo_id=uuid4(),
        experience_id=experience.experience_id,
        photo_url=url,
        created_at=created_at,
    )
    db.add(image)
    db.flush()
    return image


def _stored_photo(
    client_and_session,
    image_storage,
    user_id: UUID = ANA_ID,
    *,
    owned: bool = True,
) -> tuple[UUID, str]:
    """Create a photo for `user_id` and, when owned, its object in the fake S3."""
    _, session = client_and_session
    base = image_storage.base_url if owned else "https://external.example"
    url = f"{base}/experiences/{uuid4()}/foto.jpg"
    with session() as db:
        photo = _photo(db, _experience(db, user_id), url)
        db.commit()
        photo_id = photo.photo_id
    if owned:
        image_storage.objects[url] = (b"\xff\xd8\xff", "image/jpeg")
    return photo_id, url


def _delete(test_client: TestClient, photo_id: UUID | str, user_id: UUID | None):
    headers = _authorization(user_id) if user_id is not None else {}
    return test_client.delete(f"/experiences/images/{photo_id}", headers=headers)


def _deleted_at(session: SessionFactory, photo_id: UUID) -> datetime | None:
    with session() as db:
        return db.get(ExperienceImagesModel, photo_id).deleted_at


def _gallery_urls(test_client: TestClient) -> list[str]:
    response = test_client.get(
        f"/events/{EVENT_ID}/photos", headers=_authorization(OUTSIDER_ID)
    )
    return [item["photo_url"] for item in response.json()["items"]]


def test_author_removes_photo_and_gets_204_without_body(client, image_storage) -> None:
    test_client, session = client
    photo_id, url = _stored_photo(client, image_storage)

    response = _delete(test_client, photo_id, ANA_ID)

    assert response.status_code == 204
    assert response.content == b""
    assert _deleted_at(session, photo_id) is not None
    assert _gallery_urls(test_client) == []
    assert url not in image_storage.objects


def test_organizer_removes_a_photo_posted_by_a_participant(
    client, image_storage
) -> None:
    test_client, session = client
    photo_id, url = _stored_photo(client, image_storage, BRUNO_ID)

    response = _delete(test_client, photo_id, ORGANIZER_ID)

    assert response.status_code == 204
    assert _deleted_at(session, photo_id) is not None
    assert url not in image_storage.objects


@pytest.mark.parametrize("user_id", [BRUNO_ID, OUTSIDER_ID])
def test_third_party_gets_403_and_nothing_is_removed(
    client, image_storage, user_id: UUID
) -> None:
    test_client, session = client
    photo_id, url = _stored_photo(client, image_storage, ANA_ID)
    with session() as db:
        _experience(db, BRUNO_ID)
        db.commit()

    response = _delete(test_client, photo_id, user_id)

    assert response.status_code == 403
    assert response.json() == {"detail": FORBIDDEN_DETAIL}
    assert _deleted_at(session, photo_id) is None
    assert url in image_storage.objects
    assert _gallery_urls(test_client) == [url]


def test_unknown_photo_gets_404(client) -> None:
    test_client, _ = client

    response = _delete(test_client, uuid4(), ANA_ID)

    assert response.status_code == 404
    assert response.json() == {"detail": "Photo not found"}


def test_second_removal_gets_404_and_storage_is_called_once(
    client, image_storage, monkeypatch
) -> None:
    test_client, _ = client
    photo_id, url = _stored_photo(client, image_storage)
    deleted: list[str] = []
    original_delete = image_storage.delete
    monkeypatch.setattr(
        image_storage,
        "delete",
        lambda target: (deleted.append(target), original_delete(target))[1],
    )

    first = _delete(test_client, photo_id, ANA_ID)
    second = _delete(test_client, photo_id, ANA_ID)

    assert first.status_code == 204
    assert second.status_code == 404
    assert second.json() == {"detail": "Photo not found"}
    assert deleted == [url]


def test_photo_of_a_deleted_experience_gets_404(client, image_storage) -> None:
    test_client, session = client
    url = f"{image_storage.base_url}/experiences/x/foto.jpg"
    with session() as db:
        photo = _photo(db, _experience(db, ANA_ID, deleted_at=NOW), url)
        db.commit()
        photo_id = photo.photo_id

    response = _delete(test_client, photo_id, ANA_ID)

    assert response.status_code == 404
    assert response.json() == {"detail": "Photo not found"}


def test_photo_of_a_deleted_event_gets_404(client, image_storage) -> None:
    test_client, session = client
    deleted_event_id = uuid4()
    url = f"{image_storage.base_url}/experiences/y/foto.jpg"
    with session() as db:
        db.add(_event(deleted_event_id, "Evento apagado", deleted_at=NOW))
        db.flush()
        photo = _photo(db, _experience(db, ANA_ID, deleted_event_id), url)
        db.commit()
        photo_id = photo.photo_id

    response = _delete(test_client, photo_id, ORGANIZER_ID)

    assert response.status_code == 404


def test_photo_of_a_deleted_account_gets_404(client, image_storage) -> None:
    test_client, session = client
    photo_id, _ = _stored_photo(client, image_storage, ANA_ID)
    with session() as db:
        db.get(UserModel, ANA_ID).deleted_at = NOW
        db.commit()

    response = _delete(test_client, photo_id, ORGANIZER_ID)

    assert response.status_code == 404


def test_only_the_requested_photo_is_removed(client, image_storage) -> None:
    test_client, session = client
    removed_id, removed_url = _stored_photo(client, image_storage, ANA_ID)
    kept_id, kept_url = _stored_photo(client, image_storage, BRUNO_ID)

    response = _delete(test_client, removed_id, ANA_ID)

    assert response.status_code == 204
    assert _deleted_at(session, kept_id) is None
    assert _gallery_urls(test_client) == [kept_url]
    assert removed_url not in image_storage.objects
    assert kept_url in image_storage.objects


def test_storage_receives_the_photo_url(client, image_storage, monkeypatch) -> None:
    test_client, _ = client
    photo_id, url = _stored_photo(client, image_storage)
    deleted: list[str] = []
    monkeypatch.setattr(image_storage, "delete", deleted.append)

    response = _delete(test_client, photo_id, ANA_ID)

    assert response.status_code == 204
    assert deleted == [url]


def test_storage_failure_still_returns_204_and_is_logged(
    client, image_storage, monkeypatch, caplog
) -> None:
    test_client, session = client
    photo_id, _ = _stored_photo(client, image_storage)

    def failing_delete(url: str) -> None:
        raise RuntimeError("S3 is down")

    monkeypatch.setattr(image_storage, "delete", failing_delete)

    with caplog.at_level(logging.ERROR, logger="app.domain.services.experience"):
        response = _delete(test_client, photo_id, ANA_ID)

    assert response.status_code == 204
    assert _deleted_at(session, photo_id) is not None
    assert _gallery_urls(test_client) == []
    assert f"Failed to delete S3 object of photo {photo_id}" in caplog.text


def test_url_outside_the_bucket_is_not_sent_to_storage(
    client, image_storage, monkeypatch
) -> None:
    test_client, session = client
    photo_id, _ = _stored_photo(client, image_storage, owned=False)
    deleted: list[str] = []
    monkeypatch.setattr(image_storage, "delete", deleted.append)

    response = _delete(test_client, photo_id, ANA_ID)

    assert response.status_code == 204
    assert _deleted_at(session, photo_id) is not None
    assert deleted == []


def test_missing_token_gets_401(client, image_storage) -> None:
    test_client, session = client
    photo_id, url = _stored_photo(client, image_storage)

    response = _delete(test_client, photo_id, None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert _deleted_at(session, photo_id) is None
    assert url in image_storage.objects


def test_invalid_token_gets_401(client, image_storage) -> None:
    test_client, _ = client
    photo_id, _ = _stored_photo(client, image_storage)

    response = test_client.delete(
        f"/experiences/images/{photo_id}",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_removal_lost_to_a_concurrent_request_gets_404_and_keeps_the_file(
    client, image_storage, monkeypatch
) -> None:
    test_client, _ = client
    photo_id, url = _stored_photo(client, image_storage)
    monkeypatch.setattr(
        SqlAlchemyExperienceRepository, "soft_delete_photo", lambda self, _id: False
    )

    response = _delete(test_client, photo_id, ANA_ID)

    assert response.status_code == 404
    assert response.json() == {"detail": "Photo not found"}
    assert url in image_storage.objects
