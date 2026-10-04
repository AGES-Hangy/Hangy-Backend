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
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventInviteLinkModel,
    EventModel,
    EventParticipantModel,
    NotificationModel,
    UserModel,
)
from app.main import app


@pytest.fixture
def invite_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


def authorization(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def create_invite(
    db: Session,
    *,
    max_participants: int | None = None,
    expires_at: datetime | None = None,
) -> tuple[str, UUID, UUID]:
    organizer_id = uuid4()
    event_id = uuid4()
    token = f"invite-{uuid4()}"
    now = datetime.now(UTC)
    db.add(
        UserModel(
            user_id=organizer_id,
            user_type=UserTypeEnum.PERSONAL,
            role=UserRoleEnum.USER,
            email=f"{organizer_id}@hangy.test",
            password_hash="hash",
            name="Ana",
        )
    )
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=organizer_id,
            event_title="Pelada no Parcao",
            event_latitude=-30.0277,
            event_longitude=-51.2287,
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=2),
            max_participants=max_participants,
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=EventPrivacyEnum.INVITE_ONLY,
        )
    )
    db.add(
        EventInviteLinkModel(
            event_id=event_id,
            created_by=organizer_id,
            token=token,
            expires_at=expires_at or now + timedelta(days=1),
        )
    )
    db.commit()
    return token, event_id, organizer_id


def add_user(db: Session) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=UserTypeEnum.PERSONAL,
            role=UserRoleEnum.USER,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name="Bia",
        )
    )
    db.commit()
    return user_id


def test_accepting_a_valid_link_confirms_participant_and_notifies_organizer(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = invite_client
    with session_factory() as db:
        token, event_id, organizer_id = create_invite(db)
        guest_id = add_user(db)

    response = client.post(f"/invites/{token}/accept", headers=authorization(guest_id))

    assert response.status_code == 200
    assert response.json()["event_id"] == str(event_id)
    assert response.json()["status"] == "CONFIRMED"
    with session_factory() as db:
        participant = db.scalar(select(EventParticipantModel))
        assert participant is not None
        assert participant.user_id == guest_id
        assert participant.status is EventParticipantStatusEnum.CONFIRMED
        notification = db.scalar(select(NotificationModel))
        assert notification is not None
        assert notification.user_id == organizer_id
        assert notification.type is NotificationTypeEnum.EVENT_PARTICIPANT_JOINED


def test_expired_link_returns_gone(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = invite_client
    with session_factory() as db:
        token, _, _ = create_invite(
            db, expires_at=datetime.now(UTC) - timedelta(minutes=1)
        )
        guest_id = add_user(db)

    response = client.post(f"/invites/{token}/accept", headers=authorization(guest_id))

    assert response.status_code == 410
    assert response.json() == {"detail": "Invite link expired"}


def test_accepting_twice_returns_conflict(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = invite_client
    with session_factory() as db:
        token, _, _ = create_invite(db)
        guest_id = add_user(db)

    assert (
        client.post(
            f"/invites/{token}/accept", headers=authorization(guest_id)
        ).status_code
        == 200
    )
    response = client.post(f"/invites/{token}/accept", headers=authorization(guest_id))

    assert response.status_code == 409
    assert response.json() == {"detail": "Invite already accepted"}


def test_accepting_a_full_event_returns_conflict(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = invite_client
    with session_factory() as db:
        token, event_id, _ = create_invite(db, max_participants=1)
        confirmed_user_id = add_user(db)
        guest_id = add_user(db)
        db.add(
            EventParticipantModel(
                event_id=event_id,
                user_id=confirmed_user_id,
                status=EventParticipantStatusEnum.CONFIRMED,
            )
        )
        db.commit()

    response = client.post(f"/invites/{token}/accept", headers=authorization(guest_id))

    assert response.status_code == 409
    assert response.json() == {"detail": "Event is full"}


def test_unknown_link_returns_not_found(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = invite_client
    with session_factory() as db:
        guest_id = add_user(db)

    response = client.post("/invites/unknown/accept", headers=authorization(guest_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "Invite link not found"}


def test_openapi_documents_invite_acceptance(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = invite_client

    operation = client.get("/openapi.json").json()["paths"]["/invites/{token}/accept"][
        "post"
    ]

    assert set(operation["responses"]) >= {"200", "401", "404", "409", "410", "422"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AcceptInviteOutput"
    }
