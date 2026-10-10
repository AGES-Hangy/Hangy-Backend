from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, select
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
    EventExperienceModel,
    EventModel,
    EventParticipantModel,
    UserModel,
)
from app.main import app

ORGANIZER_ID = UUID("a9100000-0000-4000-8000-000000000001")
PARTICIPANT_ID = UUID("a9100000-0000-4000-8000-000000000002")
OUTSIDER_ID = UUID("a9100000-0000-4000-8000-000000000003")
EVENT_ID = UUID("a9100000-0000-4000-8000-000000000004")
PARTICIPATION_ID = UUID("a9100000-0000-4000-8000-000000000005")
PATH = f"/events/{EVENT_ID}/experiences"


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
        for user_id, name in (
            (ORGANIZER_ID, "Organizador"),
            (PARTICIPANT_ID, "Participante"),
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
        now = datetime.now(UTC)
        db.add(
            EventModel(
                event_id=EVENT_ID,
                event_creator_id=ORGANIZER_ID,
                event_title="Pelada encerrada",
                event_latitude=0.0,
                event_longitude=0.0,
                starts_at=now - timedelta(hours=3),
                ends_at=now - timedelta(hours=1),
                max_participants=None,
                event_status=EventStatusEnum.PUBLISHED,
                event_privacy=EventPrivacyEnum.PUBLIC,
            )
        )
        db.add(
            EventParticipantModel(
                participant_id=PARTICIPATION_ID,
                event_id=EVENT_ID,
                user_id=PARTICIPANT_ID,
                status=EventParticipantStatusEnum.CONFIRMED,
            )
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


def _authorization(user_id: UUID = PARTICIPANT_ID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _post(
    test_client: TestClient,
    user_id: UUID = PARTICIPANT_ID,
    description: str = "Melhor pelada do ano",
):
    return test_client.post(
        PATH,
        json={"description": description},
        headers=_authorization(user_id),
    )


def test_confirmed_participant_can_create_experience_after_event_ends(client) -> None:
    test_client, session_factory = client

    response = _post(test_client)

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "experience_id": body["experience_id"],
        "event_id": str(EVENT_ID),
        "description": "Melhor pelada do ano",
        "images": [],
        "created_at": body["created_at"],
    }
    UUID(body["experience_id"])
    created_at = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
    assert created_at.utcoffset() == timedelta(0)
    with session_factory() as db:
        model = db.get(EventExperienceModel, UUID(body["experience_id"]))
        assert model is not None
        assert model.event_participant_id == PARTICIPATION_ID
        assert model.description == "Melhor pelada do ano"


def test_explicitly_finished_event_can_have_an_experience(client) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        event = db.get(EventModel, EVENT_ID)
        event.event_status = EventStatusEnum.FINISHED
        event.ends_at = datetime.now(UTC) + timedelta(hours=1)
        db.commit()

    assert _post(test_client).status_code == 201


def test_event_that_has_not_ended_returns_400(client) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        event = db.get(EventModel, EVENT_ID)
        event.ends_at = datetime.now(UTC) + timedelta(hours=1)
        db.commit()

    response = _post(test_client)

    assert response.status_code == 400
    assert response.json() == {"detail": "Event has not finished yet"}
    with session_factory() as db:
        assert db.scalars(select(EventExperienceModel)).all() == []


@pytest.mark.parametrize(
    "participation_status",
    [
        EventParticipantStatusEnum.PENDING,
        EventParticipantStatusEnum.CANCELLED,
        EventParticipantStatusEnum.REJECTED,
        EventParticipantStatusEnum.REMOVED,
    ],
)
def test_only_confirmed_participants_can_post(client, participation_status) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        participant = db.get(EventParticipantModel, PARTICIPATION_ID)
        participant.status = participation_status
        db.commit()

    response = _post(test_client)

    assert response.status_code == 403
    assert response.json() == {"detail": "Only confirmed participants can post"}
    with session_factory() as db:
        assert db.scalars(select(EventExperienceModel)).all() == []


def test_nonparticipant_cannot_post(client) -> None:
    test_client, _ = client

    response = _post(test_client, OUTSIDER_ID)

    assert response.status_code == 403
    assert response.json() == {"detail": "Only confirmed participants can post"}


@pytest.mark.parametrize(
    "event_status", [EventStatusEnum.DRAFT, EventStatusEnum.CANCELLED]
)
def test_unavailable_event_returns_404(client, event_status) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        event = db.get(EventModel, EVENT_ID)
        event.event_status = event_status
        db.commit()

    response = _post(test_client)

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_missing_and_deleted_event_return_404(client) -> None:
    test_client, session_factory = client
    missing = test_client.post(
        f"/events/{uuid4()}/experiences",
        json={"description": "Texto"},
        headers=_authorization(),
    )
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Event not found"}

    with session_factory() as db:
        event = db.get(EventModel, EVENT_ID)
        event.deleted_at = datetime.now(UTC)
        db.commit()
    deleted = _post(test_client)
    assert deleted.status_code == 404
    assert deleted.json() == {"detail": "Event not found"}


def test_invite_only_event_is_hidden_from_nonparticipant(client) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        event = db.get(EventModel, EVENT_ID)
        event.event_privacy = EventPrivacyEnum.INVITE_ONLY
        db.commit()

    response = _post(test_client, OUTSIDER_ID)

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}
    assert _post(test_client).status_code == 201


def test_event_is_hidden_when_organizer_blocked_the_participant(client) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_block = Table(
            "user_block",
            MetaData(),
            Column("blocker_id", Uuid, nullable=False),
            Column("blocked_id", Uuid, nullable=False),
        )
        user_block.create(db.get_bind())
        db.execute(
            user_block.insert().values(
                blocker_id=ORGANIZER_ID, blocked_id=PARTICIPANT_ID
            )
        )
        db.commit()

    response = _post(test_client)

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_missing_or_invalid_token_returns_401(client) -> None:
    test_client, _ = client

    missing = test_client.post(PATH, json={"description": "Texto"})
    invalid = test_client.post(
        PATH,
        json={"description": "Texto"},
        headers={"Authorization": "Bearer invalid"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert (
        missing.json() == invalid.json() == {"detail": "Could not validate credentials"}
    )


def test_second_experience_for_same_participant_returns_409(client) -> None:
    test_client, session_factory = client
    first = _post(test_client)

    second = _post(test_client, description="Outra descrição")

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {"detail": "Experience already exists"}
    with session_factory() as db:
        models = db.scalars(select(EventExperienceModel)).all()
        assert len(models) == 1
        assert models[0].description == "Melhor pelada do ano"


@pytest.mark.parametrize("description", [" ", "x" * 1001])
def test_description_must_fit_database_column(client, description) -> None:
    test_client, session_factory = client

    response = _post(test_client, description=description)

    assert response.status_code == 422
    with session_factory() as db:
        assert db.scalars(select(EventExperienceModel)).all() == []
