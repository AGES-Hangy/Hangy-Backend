from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import UserConnectionStatusEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import NotificationModel, UserConnectionModel
from app.main import app

TERMS_VERSION = "2026-08-01"

USER_A = {
    "user_type": "PERSONAL",
    "email": "alice@hangy.com",
    "password": "strong-password",
    "name": "Alice",
    "cpf": "52998224725",
    "date_of_birth": "2000-01-01",
    "state": "RS",
    "city": "Porto Alegre",
    "accepted_terms_version": TERMS_VERSION,
}

USER_B = {
    "user_type": "PERSONAL",
    "email": "bruno@hangy.com",
    "password": "strong-password",
    "name": "Bruno",
    "cpf": "11144477735",
    "date_of_birth": "1998-05-20",
    "state": "RS",
    "city": "Porto Alegre",
    "accepted_terms_version": TERMS_VERSION,
}

BUSINESS_USER = {
    "user_type": "BUSINESS",
    "email": "bar@hangy.com",
    "password": "strong-password",
    "business_name": "Bar do Ze",
    "cnpj": "11222333000181",
    "description": "Bar e petiscaria",
    "location": {"latitude": -30.0331, "longitude": -51.23},
    "address": "Av. Independencia, 100",
    "accepted_terms_version": TERMS_VERSION,
}


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


def register_and_authenticate(
    client: TestClient, payload: dict[str, str]
) -> tuple[str, str]:
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    body = response.json()
    return body["user"]["id"], body["access_token"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_send_connection_request_returns_201_with_pending_status(
    client: TestClient,
) -> None:
    user_a_id, token_a = register_and_authenticate(client, USER_A)
    user_b_id, token_b = register_and_authenticate(client, USER_B)

    response = client.post(
        "/connections",
        json={"receiver_id": user_b_id},
        headers=auth_headers(token_a),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["requester_id"] == user_a_id
    assert body["receiver_id"] == user_b_id
    assert body["status"] == "PENDING"
    assert body["connection_id"]
    assert body["created_at"]


def test_send_connection_request_to_self_returns_400(client: TestClient) -> None:
    user_a_id, token_a = register_and_authenticate(client, USER_A)

    response = client.post(
        "/connections",
        json={"receiver_id": user_a_id},
        headers=auth_headers(token_a),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot send a connection request to yourself"}


def test_second_connection_request_in_either_direction_returns_409(
    client: TestClient,
) -> None:
    user_a_id, token_a = register_and_authenticate(client, USER_A)
    user_b_id, token_b = register_and_authenticate(client, USER_B)

    first = client.post(
        "/connections",
        json={"receiver_id": user_b_id},
        headers=auth_headers(token_a),
    )
    assert first.status_code == 201

    same_direction = client.post(
        "/connections",
        json={"receiver_id": user_b_id},
        headers=auth_headers(token_a),
    )
    opposite_direction = client.post(
        "/connections",
        json={"receiver_id": user_a_id},
        headers=auth_headers(token_b),
    )

    assert same_direction.status_code == 409
    assert opposite_direction.status_code == 409
    assert same_direction.json() == {"detail": "Connection already exists"}
    assert opposite_direction.json() == {"detail": "Connection already exists"}


def test_send_connection_request_to_nonexistent_user_returns_404(
    client: TestClient,
) -> None:
    _, token_a = register_and_authenticate(client, USER_A)

    response = client.post(
        "/connections",
        json={"receiver_id": str(uuid4())},
        headers=auth_headers(token_a),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_send_connection_request_to_business_user_returns_404(
    client: TestClient,
) -> None:
    _, token_a = register_and_authenticate(client, USER_A)
    business_id, _ = register_and_authenticate(client, BUSINESS_USER)

    response = client.post(
        "/connections",
        json={"receiver_id": business_id},
        headers=auth_headers(token_a),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_send_connection_request_to_blocker_returns_404(client: TestClient) -> None:
    user_a_id, token_a = register_and_authenticate(client, USER_A)
    user_b_id, token_b = register_and_authenticate(client, USER_B)
    block = client.post(f"/users/{user_a_id}/block", headers=auth_headers(token_b))
    assert block.status_code == 204

    response = client.post(
        "/connections",
        json={"receiver_id": user_b_id},
        headers=auth_headers(token_a),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_send_connection_request_to_blocked_user_returns_404(
    client: TestClient,
) -> None:
    _, token_a = register_and_authenticate(client, USER_A)
    user_b_id, _ = register_and_authenticate(client, USER_B)
    block = client.post(f"/users/{user_b_id}/block", headers=auth_headers(token_a))
    assert block.status_code == 204

    response = client.post(
        "/connections",
        json={"receiver_id": user_b_id},
        headers=auth_headers(token_a),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}

def open_db() -> AbstractContextManager[Session]:
    # Reuses the in-memory session factory the `client` fixture installed.
    return contextmanager(app.dependency_overrides[get_db])()


def send_request(client: TestClient, token: str, receiver_id: str) -> str:
    response = client.post(
        "/connections",
        json={"receiver_id": receiver_id},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    return response.json()["connection_id"]


def confirm_connection(connection_id: str) -> None:
    # There is no accept endpoint yet, so the CONFIRMED state is seeded.
    with open_db() as db:
        model = db.get(UserConnectionModel, UUID(connection_id))
        assert model is not None
        model.status = UserConnectionStatusEnum.CONFIRMED
        db.commit()


def list_connection_ids(client: TestClient, token: str) -> list[str]:
    response = client.get("/users/me/connections", headers=auth_headers(token))
    assert response.status_code == 200
    return [item["user_id"] for item in response.json()["items"]]


def test_requester_can_cancel_pending_request_returns_204(client: TestClient) -> None:
    _, token_a = register_and_authenticate(client, USER_A)
    user_b_id, _ = register_and_authenticate(client, USER_B)
    connection_id = send_request(client, token_a, user_b_id)

    response = client.delete(
        f"/connections/{connection_id}", headers=auth_headers(token_a)
    )

    assert response.status_code == 204
    assert response.content == b""


def test_receiver_can_remove_pending_request_returns_204(client: TestClient) -> None:
    _, token_a = register_and_authenticate(client, USER_A)
    user_b_id, token_b = register_and_authenticate(client, USER_B)
    connection_id = send_request(client, token_a, user_b_id)

    response = client.delete(
        f"/connections/{connection_id}", headers=auth_headers(token_b)
    )

    assert response.status_code == 204


@pytest.mark.parametrize("undoing_side", ["requester", "receiver"])
def test_undo_confirmed_connection_removes_it_from_both_lists(
    client: TestClient, undoing_side: str
) -> None:
    user_a_id, token_a = register_and_authenticate(client, USER_A)
    user_b_id, token_b = register_and_authenticate(client, USER_B)
    connection_id = send_request(client, token_a, user_b_id)
    confirm_connection(connection_id)
    assert list_connection_ids(client, token_a) == [user_b_id]
    assert list_connection_ids(client, token_b) == [user_a_id]
    token = token_a if undoing_side == "requester" else token_b

    response = client.delete(
        f"/connections/{connection_id}", headers=auth_headers(token)
    )

    assert response.status_code == 204
    assert list_connection_ids(client, token_a) == []
    assert list_connection_ids(client, token_b) == []


def test_undo_sets_deleted_at_and_frees_the_pair_for_a_new_request(
    client: TestClient,
) -> None:
    user_a_id, token_a = register_and_authenticate(client, USER_A)
    user_b_id, token_b = register_and_authenticate(client, USER_B)
    connection_id = send_request(client, token_a, user_b_id)

    response = client.delete(
        f"/connections/{connection_id}", headers=auth_headers(token_a)
    )
    assert response.status_code == 204

    with open_db() as db:
        model = db.get(UserConnectionModel, UUID(connection_id))
        assert model is not None
        assert model.deleted_at is not None
        # The row is kept and the status is untouched: undoing is not a status.
        assert model.status is UserConnectionStatusEnum.PENDING

    new_request = client.post(
        "/connections",
        json={"receiver_id": user_a_id},
        headers=auth_headers(token_b),
    )
    assert new_request.status_code == 201
    assert new_request.json()["connection_id"] != connection_id


def test_undo_does_not_create_notifications(client: TestClient) -> None:
    _, token_a = register_and_authenticate(client, USER_A)
    user_b_id, token_b = register_and_authenticate(client, USER_B)
    connection_id = send_request(client, token_a, user_b_id)
    with open_db() as db:
        before = db.query(NotificationModel).count()

    response = client.delete(
        f"/connections/{connection_id}", headers=auth_headers(token_b)
    )
    assert response.status_code == 204

    with open_db() as db:
        assert db.query(NotificationModel).count() == before


def test_undo_by_third_user_returns_403(client: TestClient) -> None:
    _, token_a = register_and_authenticate(client, USER_A)
    user_b_id, _ = register_and_authenticate(client, USER_B)
    _, token_c = register_and_authenticate(
        client,
        {**USER_A, "email": "carla@hangy.com", "name": "Carla", "cpf": "39053344705"},
    )
    connection_id = send_request(client, token_a, user_b_id)

    response = client.delete(
        f"/connections/{connection_id}", headers=auth_headers(token_c)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Not part of this connection"}
    with open_db() as db:
        model = db.get(UserConnectionModel, UUID(connection_id))
        assert model is not None
        assert model.deleted_at is None


def test_undo_unknown_connection_returns_404(client: TestClient) -> None:
    _, token_a = register_and_authenticate(client, USER_A)

    response = client.delete(f"/connections/{uuid4()}", headers=auth_headers(token_a))

    assert response.status_code == 404
    assert response.json() == {"detail": "Connection not found"}


def test_undo_already_undone_connection_returns_404(client: TestClient) -> None:
    _, token_a = register_and_authenticate(client, USER_A)
    user_b_id, token_b = register_and_authenticate(client, USER_B)
    connection_id = send_request(client, token_a, user_b_id)
    first = client.delete(
        f"/connections/{connection_id}", headers=auth_headers(token_a)
    )
    assert first.status_code == 204

    # Neither side can undo it a second time.
    for token in (token_a, token_b):
        response = client.delete(
            f"/connections/{connection_id}", headers=auth_headers(token)
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Connection not found"}


def test_undo_without_token_returns_401(client: TestClient) -> None:
    response = client.delete(f"/connections/{uuid4()}")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
