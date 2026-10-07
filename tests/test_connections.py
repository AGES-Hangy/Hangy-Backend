from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
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


@pytest.mark.skip(
    reason=(
        "USER_BLOCK (task 087) ainda não existe no banco: o repositório só tem "
        "o ponto de extensão (sempre retorna 'não bloqueado'), sem tabela pra "
        "exercitar o cenário de bloqueio de verdade."
    )
)
def test_send_connection_request_to_blocker_returns_404(client: TestClient) -> None:
    pass
