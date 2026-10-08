from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import UserConnectionStatusEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    NotificationModel,
    UserBlockModel,
    UserConnectionModel,
)
from app.main import app

USER_A_EMAIL = "ana@hangy.com"
USER_B_EMAIL = "bruno@hangy.com"
USER_PASSWORD = "strong-password"


@pytest.fixture
def client() -> Iterator[TestClient]:
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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def db_session() -> Iterator[Session]:
    return app.dependency_overrides[get_db]()


def register_user(client: TestClient, email: str, cpf: str) -> str:
    response = client.post(
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": email,
            "password": USER_PASSWORD,
            "name": "Usuário de Teste",
            "cpf": cpf,
            "phone": "51999990000",
            "date_of_birth": "2000-04-12",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": "2026-08-01",
        },
    )
    assert response.status_code == 201
    return response.json()["user"]["id"]


def login(client: TestClient, email: str) -> str:
    response = client.post(
        "/auth/login",
        json={"email": email, "password": USER_PASSWORD},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_block_creates_the_block_row_and_returns_204(client: TestClient) -> None:
    user_a_id = register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)

    response = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))

    assert response.status_code == 204

    db_generator = db_session()
    db = next(db_generator)
    try:
        block = db.scalar(select(UserBlockModel))
    finally:
        db_generator.close()

    assert block is not None
    assert str(block.blocker_id) == user_a_id
    assert str(block.blocked_id) == user_b_id


def test_block_self_returns_400(client: TestClient) -> None:
    user_id = register_user(client, USER_A_EMAIL, "52998224725")
    token = login(client, USER_A_EMAIL)

    response = client.post(f"/users/{user_id}/block", headers=auth_headers(token))

    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot block yourself"}


def test_block_nonexistent_user_returns_404(client: TestClient) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    token = login(client, USER_A_EMAIL)

    response = client.post(
        "/users/00000000-0000-0000-0000-000000000000/block",
        headers=auth_headers(token),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_block_without_token_returns_401(client: TestClient) -> None:
    user_id = register_user(client, USER_A_EMAIL, "52998224725")

    response = client.post(f"/users/{user_id}/block")

    assert response.status_code == 401


def test_block_undoes_an_existing_connection(client: TestClient) -> None:
    user_a_id = register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)

    db_generator = db_session()
    db = next(db_generator)
    try:
        connection = UserConnectionModel(
            requester_id=UUID(user_a_id),
            receiver_id=UUID(user_b_id),
            status=UserConnectionStatusEnum.CONFIRMED,
        )
        db.add(connection)
        db.commit()
        connection_id = connection.connection_id
    finally:
        db_generator.close()

    response = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert response.status_code == 204

    db_generator = db_session()
    db = next(db_generator)
    try:
        reloaded = db.scalar(
            select(UserConnectionModel).where(
                UserConnectionModel.connection_id == connection_id
            )
        )
    finally:
        db_generator.close()

    assert reloaded is not None
    assert reloaded.deleted_at is not None


def test_block_creates_no_notification_for_the_blocked_user(
    client: TestClient,
) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)

    response = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert response.status_code == 204

    db_generator = db_session()
    db = next(db_generator)
    try:
        notifications = db.scalars(
            select(NotificationModel).where(
                NotificationModel.user_id == UUID(user_b_id)
            )
        ).all()
    finally:
        db_generator.close()

    assert notifications == []
