"""Tests for PATCH /connections/{connection_id}.

Follows the pattern from tests/test_connections_pending.py:
- SQLite in-memory with StaticPool
- Manually minted JWTs to avoid round-tripping /register
- Connection rows inserted directly for exact control over status
"""

from __future__ import annotations

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
    NotificationTypeEnum,
    UserConnectionStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    NotificationModel,
    UserConnectionModel,
    UserModel,
)
from app.main import app

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def answer_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


def make_token(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=30)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def create_user(
    db: Session,
    name: str = "Test User",
    user_id: UUID | None = None,
) -> UserModel:
    user = UserModel(
        user_id=user_id or uuid4(),
        user_type=UserTypeEnum.PERSONAL,
        role=UserRoleEnum.USER,
        email=f"{uuid4()}@test.com",
        password_hash="hashed",
        name=name,
    )
    db.add(user)
    db.flush()
    return user


def add_connection(
    db: Session,
    requester: UserModel,
    receiver: UserModel,
    *,
    status: UserConnectionStatusEnum = UserConnectionStatusEnum.PENDING,
    connection_id: UUID | None = None,
) -> UserConnectionModel:
    connection = UserConnectionModel(
        connection_id=connection_id or uuid4(),
        requester_id=requester.user_id,
        receiver_id=receiver.user_id,
        status=status,
        created_at=NOW,
    )
    db.add(connection)
    db.flush()
    return connection


def url(connection_id: UUID) -> str:
    return f"/connections/{connection_id}"


def test_receiver_accepting_a_pending_request_confirms_it(answer_client) -> None:
    client, session = answer_client
    with session() as db:
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        connection = add_connection(db, ana, bruno)
        db.commit()
        headers = make_token(bruno.user_id)
        connection_id = connection.connection_id
        requester_id = ana.user_id
        receiver_id = bruno.user_id

    response = client.patch(
        url(connection_id), json={"status": "CONFIRMED"}, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["connection_id"] == str(connection_id)
    assert body["requester_id"] == str(requester_id)
    assert body["receiver_id"] == str(receiver_id)
    assert body["status"] == "CONFIRMED"
    assert "updated_at" in body


def test_receiver_rejecting_a_pending_request_rejects_it(answer_client) -> None:
    client, session = answer_client
    with session() as db:
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        connection = add_connection(db, ana, bruno)
        db.commit()
        headers = make_token(bruno.user_id)
        connection_id = connection.connection_id

    response = client.patch(
        url(connection_id), json={"status": "REJECTED"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_accepting_notifies_the_requester(answer_client) -> None:
    client, session = answer_client
    with session() as db:
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        connection = add_connection(db, ana, bruno)
        db.commit()
        headers = make_token(bruno.user_id)
        connection_id = connection.connection_id
        requester_id = ana.user_id

    response = client.patch(
        url(connection_id), json={"status": "CONFIRMED"}, headers=headers
    )
    assert response.status_code == 200

    with session() as db:
        notifications = db.scalars(
            select(NotificationModel).where(NotificationModel.user_id == requester_id)
        ).all()
    assert len(notifications) == 1
    assert notifications[0].type == NotificationTypeEnum.CONNECTION_ACCEPTED


def test_rejecting_does_not_notify_the_requester(answer_client) -> None:
    client, session = answer_client
    with session() as db:
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        connection = add_connection(db, ana, bruno)
        db.commit()
        headers = make_token(bruno.user_id)
        connection_id = connection.connection_id
        requester_id = ana.user_id

    response = client.patch(
        url(connection_id), json={"status": "REJECTED"}, headers=headers
    )
    assert response.status_code == 200

    with session() as db:
        notifications = db.scalars(
            select(NotificationModel).where(NotificationModel.user_id == requester_id)
        ).all()
    assert notifications == []


def test_requester_cannot_answer_their_own_request(answer_client) -> None:
    client, session = answer_client
    with session() as db:
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        connection = add_connection(db, ana, bruno)
        db.commit()
        headers = make_token(ana.user_id)
        connection_id = connection.connection_id

    response = client.patch(
        url(connection_id), json={"status": "CONFIRMED"}, headers=headers
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only the receiver can answer"}


def test_unrelated_user_cannot_answer(answer_client) -> None:
    client, session = answer_client
    with session() as db:
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        carla = create_user(db, "Carla")
        connection = add_connection(db, ana, bruno)
        db.commit()
        headers = make_token(carla.user_id)
        connection_id = connection.connection_id

    response = client.patch(
        url(connection_id), json={"status": "CONFIRMED"}, headers=headers
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only the receiver can answer"}


def test_unknown_connection_returns_404(answer_client) -> None:
    client, session = answer_client
    with session() as db:
        bruno = create_user(db, "Bruno")
        db.commit()
        headers = make_token(bruno.user_id)

    response = client.patch(url(uuid4()), json={"status": "CONFIRMED"}, headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Connection not found"}


@pytest.mark.parametrize(
    "existing_status",
    [UserConnectionStatusEnum.CONFIRMED, UserConnectionStatusEnum.REJECTED],
)
def test_answering_an_already_answered_request_returns_409(
    answer_client, existing_status: UserConnectionStatusEnum
) -> None:
    client, session = answer_client
    with session() as db:
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        connection = add_connection(db, ana, bruno, status=existing_status)
        db.commit()
        headers = make_token(bruno.user_id)
        connection_id = connection.connection_id

    response = client.patch(
        url(connection_id), json={"status": "CONFIRMED"}, headers=headers
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Connection is not pending"}


def test_status_other_than_confirmed_or_rejected_is_rejected_by_validation(
    answer_client,
) -> None:
    client, session = answer_client
    with session() as db:
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        connection = add_connection(db, ana, bruno)
        db.commit()
        headers = make_token(bruno.user_id)
        connection_id = connection.connection_id

    response = client.patch(
        url(connection_id), json={"status": "PENDING"}, headers=headers
    )

    assert response.status_code == 422


def test_missing_token_returns_401(answer_client) -> None:
    client, _ = answer_client

    response = client.patch(url(uuid4()), json={"status": "CONFIRMED"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
