from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.domain.enums import EventStatusEnum, UserRoleEnum, UserTypeEnum
from app.infrastructure.repository.models import EventModel, UserModel
from tests import test_create_event
from tests.test_create_event import RUNNING_ID, auth_header, payload


@pytest.fixture
def event_client() -> tuple[TestClient, sessionmaker[Session]]:
    yield from test_create_event.client.__wrapped__()


def create_event(test_client: TestClient) -> UUID:
    response = test_client.post("/events", json=payload(), headers=auth_header())
    assert response.status_code == 201
    return UUID(response.json()["event_id"])


def header_for(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def test_organizer_can_update_event_fields_and_tags(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    starts_at = datetime.now(UTC) + timedelta(days=3)

    response = test_client.patch(
        f"/events/{event_id}",
        json={
            "title": "Pelada no Parcao - novo horario",
            "description": "Agora no campo 2",
            "event_date": starts_at.isoformat(),
            "end_date": (starts_at + timedelta(hours=2)).isoformat(),
            "location": {"latitude": -30.03, "longitude": -51.22},
            "location_name": "Campo 2",
            "cover_photo_url": "https://storage/new-cover.png",
            "tag_ids": [str(RUNNING_ID)],
        },
        headers=auth_header(),
    )

    assert response.status_code == 200
    response_body = response.json()
    assert response_body["event_id"] == str(event_id)
    assert response_body["title"] == "Pelada no Parcao - novo horario"
    assert response_body["status"] == "PUBLISHED"
    assert response_body["updated_at"] is not None
    assert datetime.fromisoformat(response_body["event_date"]).replace(tzinfo=UTC) == (
        starts_at
    )

    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_description == "Agora no campo 2"
        assert event.location_name == "Campo 2"
        assert event.cover_photo_url == "https://storage/new-cover.png"
        assert event.event_latitude == -30.03
        assert event.event_longitude == -51.22
        assert [tag.tag_id for tag in event.tags] == [RUNNING_ID]


def test_organizer_can_clear_nullable_event_fields(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)

    response = test_client.patch(
        f"/events/{event_id}",
        json={
            "description": None,
            "location_name": None,
            "cover_photo_url": None,
            "tag_ids": [],
        },
        headers=auth_header(),
    )

    assert response.status_code == 200
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_description is None
        assert event.location_name is None
        assert event.cover_photo_url is None
        assert event.tags == []


def test_only_the_organizer_can_update_an_event(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    other_user_id = uuid4()
    with session_factory() as db:
        db.add(
            UserModel(
                user_id=other_user_id,
                user_type=UserTypeEnum.PERSONAL,
                role=UserRoleEnum.USER,
                email="other@hangy.test",
                password_hash="hash",
                name="Outra Pessoa",
            )
        )
        db.commit()

    response = test_client.patch(
        f"/events/{event_id}",
        json={"title": "Tentativa"},
        headers=header_for(other_user_id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only the organizer can edit this event"}


def test_an_event_cannot_be_moved_to_the_past(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = event_client
    event_id = create_event(test_client)

    response = test_client.patch(
        f"/events/{event_id}",
        json={"event_date": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
        headers=auth_header(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Event date must be in the future"}


def test_a_finished_event_cannot_be_updated(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        event.event_status = EventStatusEnum.FINISHED
        db.commit()

    response = test_client.patch(
        f"/events/{event_id}",
        json={"title": "Tentativa"},
        headers=auth_header(),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Event already finished"}


def test_an_unknown_event_cannot_be_updated(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = event_client

    response = test_client.patch(
        f"/events/{uuid4()}",
        json={"title": "Tentativa"},
        headers=auth_header(),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_openapi_documents_event_update(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = event_client

    operation = test_client.get("/openapi.json").json()["paths"]["/events/{event_id}"][
        "patch"
    ]

    assert set(operation["responses"]) >= {"200", "400", "403", "404", "409", "422"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UpdateEventOutput"
    }
