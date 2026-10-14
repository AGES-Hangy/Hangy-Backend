from collections.abc import Iterator
from datetime import UTC, datetime
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
    UserModel,
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


def test_block_undoes_a_pending_request_sent_by_the_blocked_user(
    client: TestClient,
) -> None:
    user_a_id = register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)

    db_generator = db_session()
    db = next(db_generator)
    try:
        db.add(
            UserConnectionModel(
                requester_id=UUID(user_b_id),
                receiver_id=UUID(user_a_id),
                status=UserConnectionStatusEnum.PENDING,
            )
        )
        db.commit()
    finally:
        db_generator.close()

    response = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert response.status_code == 204

    db_generator = db_session()
    db = next(db_generator)
    try:
        reloaded = db.scalar(select(UserConnectionModel))
    finally:
        db_generator.close()

    assert reloaded is not None
    assert reloaded.deleted_at is not None


def test_block_an_already_blocked_user_returns_409(client: TestClient) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)
    first = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert first.status_code == 204

    response = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))

    assert response.status_code == 409
    assert response.json() == {"detail": "User already blocked"}

    db_generator = db_session()
    db = next(db_generator)
    try:
        blocks = db.scalars(select(UserBlockModel)).all()
    finally:
        db_generator.close()

    assert len(blocks) == 1


def test_block_a_user_who_already_blocked_me_returns_204(client: TestClient) -> None:
    user_a_id = register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)
    token_b = login(client, USER_B_EMAIL)
    first = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert first.status_code == 204

    response = client.post(f"/users/{user_a_id}/block", headers=auth_headers(token_b))

    assert response.status_code == 204


def test_block_deleted_user_returns_404(client: TestClient) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)

    db_generator = db_session()
    db = next(db_generator)
    try:
        target = db.get(UserModel, UUID(user_b_id))
        assert target is not None
        target.deleted_at = datetime.now(UTC)
        db.commit()
    finally:
        db_generator.close()

    response = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_block_hides_the_profile_from_both_sides(client: TestClient) -> None:
    user_a_id = register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)
    token_b = login(client, USER_B_EMAIL)
    visible = client.get(f"/users/{user_b_id}", headers=auth_headers(token_a))
    assert visible.status_code == 200

    response = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert response.status_code == 204

    blocker_view = client.get(f"/users/{user_b_id}", headers=auth_headers(token_a))
    blocked_view = client.get(f"/users/{user_a_id}", headers=auth_headers(token_b))

    assert blocker_view.status_code == 404
    assert blocker_view.json() == {"detail": "User not found"}
    assert blocked_view.status_code == 404
    assert blocked_view.json() == {"detail": "User not found"}


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

def test_unblock_removes_the_block_row_and_returns_204(client: TestClient) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)
    blocked = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert blocked.status_code == 204

    response = client.delete(f"/users/{user_b_id}/block", headers=auth_headers(token_a))

    assert response.status_code == 204
    assert response.content == b""

    db_generator = db_session()
    db = next(db_generator)
    try:
        blocks = db.scalars(select(UserBlockModel)).all()
    finally:
        db_generator.close()

    assert blocks == []


def test_unblock_makes_the_profile_visible_again_for_both_sides(
    client: TestClient,
) -> None:
    user_a_id = register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)
    token_b = login(client, USER_B_EMAIL)
    client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    hidden = client.get(f"/users/{user_b_id}", headers=auth_headers(token_a))
    assert hidden.status_code == 404

    response = client.delete(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert response.status_code == 204

    blocker_view = client.get(f"/users/{user_b_id}", headers=auth_headers(token_a))
    blocked_view = client.get(f"/users/{user_a_id}", headers=auth_headers(token_b))

    assert blocker_view.status_code == 200
    assert blocked_view.status_code == 200


def test_unblock_does_not_restore_the_connection(client: TestClient) -> None:
    user_a_id = register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)

    db_generator = db_session()
    db = next(db_generator)
    try:
        db.add(
            UserConnectionModel(
                requester_id=UUID(user_a_id),
                receiver_id=UUID(user_b_id),
                status=UserConnectionStatusEnum.CONFIRMED,
            )
        )
        db.commit()
    finally:
        db_generator.close()

    blocked = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert blocked.status_code == 204

    response = client.delete(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert response.status_code == 204

    db_generator = db_session()
    db = next(db_generator)
    try:
        connections = db.scalars(select(UserConnectionModel)).all()
    finally:
        db_generator.close()

    assert len(connections) == 1
    assert connections[0].deleted_at is not None


def test_unblock_a_user_who_is_not_blocked_returns_404(client: TestClient) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)

    response = client.delete(f"/users/{user_b_id}/block", headers=auth_headers(token_a))

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_unblock_nonexistent_user_returns_404(client: TestClient) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    token_a = login(client, USER_A_EMAIL)

    response = client.delete(
        "/users/00000000-0000-0000-0000-000000000000/block",
        headers=auth_headers(token_a),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_unblock_cannot_remove_a_block_placed_by_the_other_user(
    client: TestClient,
) -> None:
    user_a_id = register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)
    token_b = login(client, USER_B_EMAIL)
    blocked = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert blocked.status_code == 204

    response = client.delete(f"/users/{user_a_id}/block", headers=auth_headers(token_b))

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}

    still_hidden = client.get(f"/users/{user_b_id}", headers=auth_headers(token_a))
    assert still_hidden.status_code == 404


def test_unblock_without_token_returns_401(client: TestClient) -> None:
    user_id = register_user(client, USER_A_EMAIL, "52998224725")

    response = client.delete(f"/users/{user_id}/block")

    assert response.status_code == 401


def test_block_again_after_unblock_returns_204(client: TestClient) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)
    client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    client.delete(f"/users/{user_b_id}/block", headers=auth_headers(token_a))

    response = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))

    assert response.status_code == 204


def test_unblock_creates_no_notification_for_the_unblocked_user(
    client: TestClient,
) -> None:
    register_user(client, USER_A_EMAIL, "52998224725")
    user_b_id = register_user(client, USER_B_EMAIL, "11144477735")
    token_a = login(client, USER_A_EMAIL)
    client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))

    response = client.delete(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert response.status_code == 204

    db_generator = db_session()
    db = next(db_generator)
    try:
        notifications = db.scalars(select(NotificationModel)).all()
    finally:
        db_generator.close()

    assert notifications == []
