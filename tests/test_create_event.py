from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import EventModel, TagModel, UserModel
from app.main import app

ORGANIZER_ID = UUID("0b2f0001-0000-4000-8000-000000000001")
ORGANIZER_NAME = "Ana Souza"
FOOTBALL_ID = UUID("a91d0002-0000-4000-8000-000000000002")
RUNNING_ID = UUID("a91d0003-0000-4000-8000-000000000003")
EXTRA_TAG_IDS = [
    UUID(f"a91d000{index}-0000-4000-8000-00000000000{index}") for index in range(4, 9)
]


@pytest.fixture
def client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        db.add(
            UserModel(
                user_id=ORGANIZER_ID,
                user_type=UserTypeEnum.PERSONAL,
                role=UserRoleEnum.USER,
                email="ana@hangy.test",
                password_hash="hash",
                name=ORGANIZER_NAME,
            )
        )
        db.add_all(
            [
                TagModel(tag_id=FOOTBALL_ID, tag_name="Futebol"),
                TagModel(tag_id=RUNNING_ID, tag_name="Corrida"),
                *[
                    TagModel(tag_id=tag_id, tag_name=f"Tag {index}")
                    for index, tag_id in enumerate(EXTRA_TAG_IDS)
                ],
            ]
        )
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


def auth_header() -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(ORGANIZER_ID), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def payload(**overrides: object) -> dict[str, object]:
    starts_at = datetime.now(UTC) + timedelta(days=1)
    body: dict[str, object] = {
        "title": "Pelada no Parcao",
        "description": "Futebol society",
        "event_date": starts_at.isoformat(),
        "end_date": (starts_at + timedelta(hours=3)).isoformat(),
        "location": {"latitude": -30.0277, "longitude": -51.2287},
        "location_name": "Parcao",
        "max_participants": 20,
        "privacy": "PUBLIC",
        "tag_ids": [str(FOOTBALL_ID)],
        "cover_photo_url": "https://storage/cover.png",
    }
    body.update(overrides)
    return body


def test_a_valid_event_is_published_with_the_requester_as_organizer(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.post("/events", json=payload(), headers=auth_header())

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Pelada no Parcao"
    assert body["status"] == "PUBLISHED"
    assert body["privacy"] == "PUBLIC"
    assert body["creator"] == {"id": str(ORGANIZER_ID), "name": ORGANIZER_NAME}

    with session_factory() as db:
        event = db.get(EventModel, UUID(body["event_id"]))
        assert event is not None
        assert event.event_creator_id == ORGANIZER_ID
        assert event.location_name == "Parcao"
        assert event.max_participants == 20
        assert [tag.tag_id for tag in event.tags] == [FOOTBALL_ID]


def test_creating_an_event_requires_authentication(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.post("/events", json=payload())

    assert response.status_code == 401


def test_a_past_event_date_returns_400(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    starts_at = datetime.now(UTC) - timedelta(days=1)

    response = test_client.post(
        "/events",
        json=payload(
            event_date=starts_at.isoformat(),
            end_date=(starts_at + timedelta(hours=3)).isoformat(),
        ),
        headers=auth_header(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Event date must be in the future"}
    with session_factory() as db:
        assert db.scalars(select(EventModel)).all() == []


def test_an_end_date_before_the_event_date_returns_400(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client
    starts_at = datetime.now(UTC) + timedelta(days=1)

    response = test_client.post(
        "/events",
        json=payload(
            event_date=starts_at.isoformat(),
            end_date=(starts_at - timedelta(hours=1)).isoformat(),
        ),
        headers=auth_header(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Event must end after it starts"}


def test_more_than_five_tags_returns_400(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    tag_ids = [str(FOOTBALL_ID), str(RUNNING_ID), *[str(t) for t in EXTRA_TAG_IDS[:4]]]
    assert len(tag_ids) == 6

    response = test_client.post(
        "/events",
        json=payload(tag_ids=tag_ids),
        headers=auth_header(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "An event accepts at most 5 tags"}
    with session_factory() as db:
        assert db.scalars(select(EventModel)).all() == []


def test_an_unknown_tag_returns_404_and_persists_nothing(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.post(
        "/events",
        json=payload(tag_ids=[str(FOOTBALL_ID), str(uuid4())]),
        headers=auth_header(),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Tag not found"}
    with session_factory() as db:
        assert db.scalars(select(EventModel)).all() == []


def test_an_event_without_max_participants_has_no_capacity_limit(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    body = payload()
    del body["max_participants"]

    response = test_client.post("/events", json=body, headers=auth_header())

    assert response.status_code == 201
    with session_factory() as db:
        event = db.get(EventModel, UUID(response.json()["event_id"]))
        assert event is not None
        assert event.max_participants is None


def test_out_of_range_coordinates_return_400(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.post(
        "/events",
        json=payload(location={"latitude": 91.0, "longitude": -51.2287}),
        headers=auth_header(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid event coordinates"}


def test_missing_required_fields_return_422_naming_them(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.post("/events", json={}, headers=auth_header())

    assert response.status_code == 422
    missing = {error["loc"][-1] for error in response.json()["detail"]}
    assert {"title", "event_date", "end_date", "location"} <= missing


def test_duplicate_tag_ids_are_stored_once(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.post(
        "/events",
        json=payload(tag_ids=[str(FOOTBALL_ID), str(FOOTBALL_ID)]),
        headers=auth_header(),
    )

    assert response.status_code == 201
    with session_factory() as db:
        event = db.get(EventModel, UUID(response.json()["event_id"]))
        assert event is not None
        assert [tag.tag_id for tag in event.tags] == [FOOTBALL_ID]


def test_openapi_documents_the_event_creation(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    operation = test_client.get("/openapi.json").json()["paths"]["/events"]["post"]

    assert set(operation["responses"]) >= {"201", "400", "404", "422"}
    assert operation["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CreateEventOutput"
    }
