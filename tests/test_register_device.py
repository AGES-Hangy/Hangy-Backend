from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserDeviceModel
from app.main import app

USER_EMAIL = "device_user@hangy.com"
USER_PASSWORD = "strong-password"
VALID_TOKEN = "ExponentPushToken[abc123]"
OTHER_TOKEN = "ExponentPushToken[xyz789]"
TERMS_VERSION = "2026-08-01"


def _personal_payload(email: str) -> dict:
    cpf_by_email = {
        "user_a@hangy.com": "52998224725",
        "user_b@hangy.com": "11144477735",
    }
    return {
        "user_type": "PERSONAL",
        "email": email,
        "password": USER_PASSWORD,
        "name": "Test User",
        "cpf": cpf_by_email.get(email, "52998224725"),
        "date_of_birth": "2000-01-01",
        "country": "BR",
        "state": "RS",
        "city": "Porto Alegre",
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


def register_and_login(client: TestClient, email: str = USER_EMAIL) -> str:
    client.post("/register", json=_personal_payload(email))
    resp = client.post("/login", json={"email": email, "password": USER_PASSWORD})
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_register_device_returns_201(client: TestClient) -> None:
    token = register_and_login(client)
    response = client.post(
        "/users/me/devices",
        json={"device_token": VALID_TOKEN, "platform": "ANDROID"},
        headers=auth_headers(token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["platform"] == "ANDROID"
    assert "device_id" in body
    assert "created_at" in body


def test_register_same_token_twice_does_not_duplicate(client: TestClient) -> None:
    token = register_and_login(client)
    headers = auth_headers(token)
    payload = {"device_token": VALID_TOKEN, "platform": "ANDROID"}

    client.post("/users/me/devices", json=payload, headers=headers)
    client.post("/users/me/devices", json=payload, headers=headers)

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        rows = db.scalars(
            select(UserDeviceModel).where(UserDeviceModel.device_token == VALID_TOKEN)
        ).all()
    finally:
        db_gen.close()

    assert len(rows) == 1


def test_token_is_reassigned_to_new_user(client: TestClient) -> None:
    token_a = register_and_login(client, "user_a@hangy.com")
    token_b = register_and_login(client, "user_b@hangy.com")

    client.post(
        "/users/me/devices",
        json={"device_token": VALID_TOKEN, "platform": "ANDROID"},
        headers=auth_headers(token_a),
    )

    resp = client.post(
        "/users/me/devices",
        json={"device_token": VALID_TOKEN, "platform": "IOS"},
        headers=auth_headers(token_b),
    )
    assert resp.status_code == 201

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        row = db.scalar(
            select(UserDeviceModel).where(UserDeviceModel.device_token == VALID_TOKEN)
        )
    finally:
        db_gen.close()

    assert row is not None
    me_b = client.get("/users/me", headers=auth_headers(token_b)).json()
    assert str(row.user_id) == me_b["user_id"]


def test_invalid_token_format_returns_422(client: TestClient) -> None:
    token = register_and_login(client)
    response = client.post(
        "/users/me/devices",
        json={"device_token": "not-a-valid-expo-token", "platform": "ANDROID"},
        headers=auth_headers(token),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid device token format"


def test_unauthenticated_request_returns_401(client: TestClient) -> None:
    response = client.post(
        "/users/me/devices",
        json={"device_token": VALID_TOKEN, "platform": "ANDROID"},
    )
    assert response.status_code == 401
