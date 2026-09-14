from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
    UserModel,
)
from app.main import app


@dataclass(frozen=True)
class EventScenario:
    event_id: UUID
    organizer_id: UUID
    confirmed_id: UUID
    pending_id: UUID
    stranger_id: UUID


@pytest.fixture
def participants_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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
        )
    )


def _create_scenario(
    db: Session, privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC
) -> EventScenario:
    scenario = EventScenario(
        event_id=uuid4(),
        organizer_id=uuid4(),
        confirmed_id=uuid4(),
        pending_id=uuid4(),
        stranger_id=uuid4(),
    )
    _add_user(db, scenario.organizer_id, "Organizadora")
    _add_user(db, scenario.confirmed_id, "Bruno Lima")
    _add_user(db, scenario.pending_id, "Pendente Souza")
    _add_user(db, scenario.stranger_id, "Estranho")

    db.add(
        EventModel(
            event_id=scenario.event_id,
            event_creator_id=scenario.organizer_id,
            event_title="Pelada no Parcao",
            event_latitude=-30.0277,
            event_longitude=-51.2287,
            starts_at=datetime.now(UTC) + timedelta(days=1),
            ends_at=datetime.now(UTC) + timedelta(days=1, hours=3),
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=privacy,
        )
    )
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
    db.commit()
    return scenario


def test_organizer_can_list_confirmed_and_pending_participants(
    participants_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participants_client
    with session_factory() as db:
        scenario = _create_scenario(db)

    confirmed_response = client.get(
        f"/events/{scenario.event_id}/participants",
        headers=_authorization(scenario.organizer_id),
    )
    assert confirmed_response.status_code == 200
    confirmed_body = confirmed_response.json()
    assert [item["user"]["id"] for item in confirmed_body["items"]] == [
        str(scenario.confirmed_id)
    ]
    assert confirmed_body["counts"] == {"CONFIRMED": 1, "PENDING": 1}

    pending_response = client.get(
        f"/events/{scenario.event_id}/participants",
        params={"status": "PENDING"},
        headers=_authorization(scenario.organizer_id),
    )
    assert pending_response.status_code == 200
    pending_body = pending_response.json()
    assert [item["user"]["id"] for item in pending_body["items"]] == [
        str(scenario.pending_id)
    ]
    assert pending_body["counts"] == {"CONFIRMED": 1, "PENDING": 1}


def test_non_organizer_requesting_pending_gets_forbidden(
    participants_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participants_client
    with session_factory() as db:
        scenario = _create_scenario(db)

    response = client.get(
        f"/events/{scenario.event_id}/participants",
        params={"status": "PENDING"},
        headers=_authorization(scenario.stranger_id),
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Only the organizer can list pending participants"
    }


def test_confirmed_participants_of_a_public_event_are_visible_to_any_authenticated_user(
    participants_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participants_client
    with session_factory() as db:
        scenario = _create_scenario(db)

    response = client.get(
        f"/events/{scenario.event_id}/participants",
        headers=_authorization(scenario.stranger_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["user"]["id"] for item in body["items"]] == [
        str(scenario.confirmed_id)
    ]
    assert body["counts"] == {"CONFIRMED": 1}


def test_invalid_status_filter_is_rejected(
    participants_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participants_client
    with session_factory() as db:
        scenario = _create_scenario(db)

    response = client.get(
        f"/events/{scenario.event_id}/participants",
        params={"status": "INVITED"},
        headers=_authorization(scenario.organizer_id),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid participant status"}


def test_cancelling_and_reconfirming_a_participant_does_not_create_a_new_row(
    participants_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participants_client
    with session_factory() as db:
        scenario = _create_scenario(db)

    with session_factory() as db:
        participant = db.scalar(
            select(EventParticipantModel).where(
                EventParticipantModel.user_id == scenario.confirmed_id,
                EventParticipantModel.event_id == scenario.event_id,
            )
        )
        assert participant is not None
        participant.status = EventParticipantStatusEnum.CANCELLED
        db.commit()

        participant.status = EventParticipantStatusEnum.CONFIRMED
        db.commit()

        rows = db.scalars(
            select(EventParticipantModel).where(
                EventParticipantModel.user_id == scenario.confirmed_id,
                EventParticipantModel.event_id == scenario.event_id,
            )
        ).all()
        assert len(rows) == 1

    response = client.get(
        f"/events/{scenario.event_id}/participants",
        headers=_authorization(scenario.organizer_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["user"]["id"] for item in body["items"]] == [
        str(scenario.confirmed_id)
    ]
    assert body["counts"]["CONFIRMED"] == 1


def test_counts_match_the_returned_list_contents(
    participants_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participants_client
    with session_factory() as db:
        scenario = _create_scenario(db)
        extra_confirmed_id = uuid4()
        _add_user(db, extra_confirmed_id, "Segundo Confirmado")
        db.add(
            EventParticipantModel(
                user_id=extra_confirmed_id,
                event_id=scenario.event_id,
                status=EventParticipantStatusEnum.CONFIRMED,
            )
        )
        db.commit()

    response = client.get(
        f"/events/{scenario.event_id}/participants",
        headers=_authorization(scenario.organizer_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["CONFIRMED"] == len(body["items"])
    assert body["counts"]["CONFIRMED"] == 2


def test_event_not_found_returns_404(
    participants_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participants_client
    with session_factory() as db:
        organizer_id = uuid4()
        _add_user(db, organizer_id, "Organizadora")
        db.commit()

    response = client.get(
        f"/events/{uuid4()}/participants",
        headers=_authorization(organizer_id),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_openapi_documents_event_participants(
    participants_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = participants_client

    operation = client.get("/openapi.json").json()["paths"][
        "/events/{event_id}/participants"
    ]["get"]

    assert set(operation["responses"]) >= {"200", "400", "401", "403", "404", "422"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EventParticipantsOutput"
    }
