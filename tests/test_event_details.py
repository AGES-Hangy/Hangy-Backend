from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine
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
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
    UserModel,
)
from app.main import app


@dataclass(frozen=True)
class EventScenario:
    event_id: UUID
    organizer_id: UUID
    viewer_id: UUID
    confirmed_id: UUID
    pending_id: UUID


@pytest.fixture
def details_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def override_get_db() -> Iterator[Session]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _authorization(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _add_user(db: Session, user_id: UUID, name: str) -> None:
    db.add(
        UserModel(
            user_id=user_id,
            user_type=UserTypeEnum.PERSONAL,
            role=UserRoleEnum.USER,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
            profile_photo_url=f"https://images.hangy.test/{user_id}.png",
        )
    )


def _create_scenario(
    db: Session,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    viewer_status: EventParticipantStatusEnum | None = None,
) -> EventScenario:
    scenario = EventScenario(
        event_id=uuid4(),
        organizer_id=uuid4(),
        viewer_id=uuid4(),
        confirmed_id=uuid4(),
        pending_id=uuid4(),
    )
    _add_user(db, scenario.organizer_id, "Ana Souza")
    _add_user(db, scenario.viewer_id, "Visitante")
    _add_user(db, scenario.confirmed_id, "Confirmado")
    _add_user(db, scenario.pending_id, "Pendente")

    tag = TagModel(tag_name="Futebol")
    event = EventModel(
        event_id=scenario.event_id,
        event_creator_id=scenario.organizer_id,
        event_title="Pelada no Parcao",
        event_description="Futebol society",
        event_latitude=-30.0277,
        event_longitude=-51.2287,
        location_name="Parcao",
        starts_at=datetime.now(UTC) + timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=1, hours=3),
        event_status=status,
        event_privacy=privacy,
        cover_photo_url="https://images.hangy.test/cover.png",
        tags=[tag],
    )
    db.add(event)
    db.add_all(
        [
            EventParticipantModel(
                user_id=scenario.confirmed_id,
                event_id=scenario.event_id,
                status=EventParticipantStatusEnum.CONFIRMED,
            ),
            EventParticipantModel(
                user_id=scenario.pending_id,
                event_id=scenario.event_id,
                status=EventParticipantStatusEnum.PENDING,
            ),
        ]
    )
    if viewer_status is not None:
        db.add(
            EventParticipantModel(
                user_id=scenario.viewer_id,
                event_id=scenario.event_id,
                status=viewer_status,
            )
        )
    db.commit()
    return scenario


def test_public_event_returns_all_details_and_confirmed_participants(
    details_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = details_client
    with session_factory() as db:
        scenario = _create_scenario(db)

    response = client.get(
        f"/events/{scenario.event_id}",
        headers=_authorization(scenario.viewer_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == str(scenario.event_id)
    assert body["title"] == "Pelada no Parcao"
    assert body["description"] == "Futebol society"
    assert body["location"] == {"latitude": -30.0277, "longitude": -51.2287}
    assert body["tags"][0]["name"] == "Futebol"
    assert body["organizer"] == {
        "id": str(scenario.organizer_id),
        "name": "Ana Souza",
        "user_type": "PERSONAL",
    }
    assert body["viewer"] == {
        "is_organizer": False,
        "participation_status": None,
        "can_see_participants": True,
        "available_action": "CONFIRM",
    }
    assert body["participants_preview"]["count"] == 1
    assert [item["user_id"] for item in body["participants_preview"]["items"]] == [
        str(scenario.confirmed_id)
    ]


def test_private_event_hides_participants_from_a_non_participant(
    details_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = details_client
    with session_factory() as db:
        scenario = _create_scenario(db, privacy=EventPrivacyEnum.PRIVATE)

    response = client.get(
        f"/events/{scenario.event_id}",
        headers=_authorization(scenario.viewer_id),
    )

    assert response.status_code == 200
    assert response.json()["description"] == "Futebol society"
    assert response.json()["event_date"] is not None
    assert response.json()["participants_preview"] is None
    assert response.json()["viewer"] == {
        "is_organizer": False,
        "participation_status": None,
        "can_see_participants": False,
        "available_action": "REQUEST",
    }


def test_invite_only_event_is_hidden_without_an_invite_and_visible_with_one(
    details_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = details_client
    with session_factory() as db:
        scenario = _create_scenario(db, privacy=EventPrivacyEnum.INVITE_ONLY)

    hidden_response = client.get(
        f"/events/{scenario.event_id}",
        headers=_authorization(scenario.viewer_id),
    )
    assert hidden_response.status_code == 404
    assert hidden_response.json() == {"detail": "Event not found"}

    with session_factory() as db:
        db.add(
            EventParticipantModel(
                user_id=scenario.viewer_id,
                event_id=scenario.event_id,
                status=EventParticipantStatusEnum.INVITED,
            )
        )
        db.commit()

    visible_response = client.get(
        f"/events/{scenario.event_id}",
        headers=_authorization(scenario.viewer_id),
    )
    assert visible_response.status_code == 200
    assert visible_response.json()["viewer"]["available_action"] == "ACCEPT_INVITE"


def test_cancelled_event_returns_gone(
    details_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = details_client
    with session_factory() as db:
        scenario = _create_scenario(db, status=EventStatusEnum.CANCELLED)

    response = client.get(
        f"/events/{scenario.event_id}",
        headers=_authorization(scenario.viewer_id),
    )

    assert response.status_code == 410
    assert response.json() == {"detail": "Event was cancelled"}


def test_event_is_hidden_when_organizer_blocked_the_viewer(
    details_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = details_client
    with session_factory() as db:
        scenario = _create_scenario(db)
        user_block = Table(
            "user_block",
            MetaData(),
            Column("blocker_id", Uuid, nullable=False),
            Column("blocked_id", Uuid, nullable=False),
        )
        user_block.create(db.get_bind())
        db.execute(
            user_block.insert().values(
                blocker_id=scenario.organizer_id,
                blocked_id=scenario.viewer_id,
            )
        )
        db.commit()

    response = client.get(
        f"/events/{scenario.event_id}",
        headers=_authorization(scenario.viewer_id),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


@pytest.mark.parametrize(
    ("as_organizer", "viewer_status", "expected_action"),
    [
        (True, None, "MANAGE"),
        (False, EventParticipantStatusEnum.CONFIRMED, "CANCEL_PRESENCE"),
    ],
)
def test_available_action_is_resolved_by_the_backend(
    details_client: tuple[TestClient, sessionmaker[Session]],
    as_organizer: bool,
    viewer_status: EventParticipantStatusEnum | None,
    expected_action: str,
) -> None:
    client, session_factory = details_client
    with session_factory() as db:
        scenario = _create_scenario(db, viewer_status=viewer_status)

    viewer_id = scenario.organizer_id if as_organizer else scenario.viewer_id
    response = client.get(
        f"/events/{scenario.event_id}",
        headers=_authorization(viewer_id),
    )

    assert response.status_code == 200
    assert response.json()["viewer"]["available_action"] == expected_action


def test_openapi_documents_event_details(
    details_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = details_client

    operation = client.get("/openapi.json").json()["paths"]["/events/{event_id}"]["get"]

    assert set(operation["responses"]) >= {"200", "401", "404", "410", "422"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EventDetailsOutput"
    }
