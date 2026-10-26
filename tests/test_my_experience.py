from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.repository.models import EventExperienceModel
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

SessionFactory = sessionmaker[Session]


@pytest.fixture
def client() -> Iterator[tuple[TestClient, SessionFactory]]:
    yield from test_delete_experience_photo.client.__wrapped__()


def _seed_experience(session: SessionFactory, user_id: UUID = ANA_ID) -> UUID:
    with session() as db:
        experience = _experience(db, user_id)
        _photo(db, experience, "https://images.hangy.test/a.jpg")
        removed = _photo(db, experience, "https://images.hangy.test/removida.jpg")
        removed.deleted_at = NOW - timedelta(minutes=1)
        db.commit()
        return experience.experience_id


def test_get_my_experience_returns_id_description_and_active_photos(client) -> None:
    test_client, session = client
    experience_id = _seed_experience(session)

    response = test_client.get(
        f"/events/{EVENT_ID}/experiences/me", headers=_authorization(ANA_ID)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["experience_id"] == str(experience_id)
    assert body["event_id"] == str(EVENT_ID)
    assert body["description"] == "Foi demais"
    assert [image["photo_url"] for image in body["images"]] == [
        "https://images.hangy.test/a.jpg"
    ]


def test_get_my_experience_without_one_returns_404(client) -> None:
    test_client, session = client
    _seed_experience(session, BRUNO_ID)

    response = test_client.get(
        f"/events/{EVENT_ID}/experiences/me", headers=_authorization(ANA_ID)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Experience not found"}


def test_get_my_experience_of_unknown_event_returns_404(client) -> None:
    test_client, _ = client

    response = test_client.get(
        f"/events/{uuid4()}/experiences/me", headers=_authorization(ANA_ID)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_get_my_experience_requires_token(client) -> None:
    test_client, _ = client

    response = test_client.get(f"/events/{EVENT_ID}/experiences/me")

    assert response.status_code == 401


def test_author_updates_description(client) -> None:
    test_client, session = client
    experience_id = _seed_experience(session)

    response = test_client.patch(
        f"/experiences/{experience_id}",
        json={"description": "  Melhor pelada do ano  "},
        headers=_authorization(ANA_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Melhor pelada do ano"
    assert body["event_id"] == str(EVENT_ID)
    assert len(body["images"]) == 1
    with session() as db:
        stored = db.scalar(
            select(EventExperienceModel.description).where(
                EventExperienceModel.experience_id == experience_id
            )
        )
    assert stored == "Melhor pelada do ano"


@pytest.mark.parametrize("user_id", [BRUNO_ID, OUTSIDER_ID])
def test_other_users_cannot_update_description(client, user_id) -> None:
    test_client, session = client
    experience_id = _seed_experience(session)

    response = test_client.patch(
        f"/experiences/{experience_id}",
        json={"description": "Invadido"},
        headers=_authorization(user_id),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Experience not found"}


@pytest.mark.parametrize("description", ["", "   ", "x" * 1001])
def test_invalid_description_returns_422(client, description) -> None:
    test_client, session = client
    experience_id = _seed_experience(session)

    response = test_client.patch(
        f"/experiences/{experience_id}",
        json={"description": description},
        headers=_authorization(ANA_ID),
    )

    assert response.status_code == 422


def test_deleted_event_hides_experience(client) -> None:
    test_client, session = client
    deleted_event = uuid4()
    with session() as db:
        db.add(_event(deleted_event, "Apagado", deleted_at=NOW))
        experience = _experience(db, ANA_ID, deleted_event)
        db.commit()
        experience_id = experience.experience_id

    response = test_client.patch(
        f"/experiences/{experience_id}",
        json={"description": "Nova"},
        headers=_authorization(ANA_ID),
    )

    assert response.status_code == 404


def test_user_photos_expose_experience_id(client) -> None:
    test_client, session = client
    experience_id = _seed_experience(session)

    response = test_client.get("/users/me/photos", headers=_authorization(ANA_ID))

    assert response.status_code == 200
    assert [item["experience_id"] for item in response.json()["items"]] == [
        str(experience_id)
    ]
