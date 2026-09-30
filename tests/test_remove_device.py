from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserDeviceModel
from app.main import app

USER_EMAIL = "remove_device_user@hangy.com"
USER_PASSWORD = "strong-password"
VALID_TOKEN = "ExponentPushToken[abc123]"
TERMS_VERSION = "2026-08-01"


CPF_BY_EMAIL = {
    "device_owner@hangy.com": "52998224725",
    "device_intruder@hangy.com": "11144477735",
}


def _personal_payload(email: str) -> dict:
    return {
        "user_type": "PERSONAL",
        "email": email,
        "password": USER_PASSWORD,
        "name": "Test User",
        "cpf": CPF_BY_EMAIL.get(email, "52998224725"),
        "date_of_birth": "2000-01-01",
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
    client.post("/auth/register", json=_personal_payload(email))
    resp = client.post("/auth/login", json={"email": email, "password": USER_PASSWORD})
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_remove_device_returns_204_and_deletes_row(client: TestClient) -> None:
    token = register_and_login(client)
    headers = auth_headers(token)
    client.post(
        "/users/me/devices",
        json={"device_token": VALID_TOKEN, "platform": "ANDROID"},
        headers=headers,
    )

    response = client.delete(f"/users/me/devices/{VALID_TOKEN}", headers=headers)
    assert response.status_code == 204

    db_gen = app.dependency_overrides[get_db]()
    db = next(db_gen)
    try:
        row = db.scalar(
            select(UserDeviceModel).where(UserDeviceModel.device_token == VALID_TOKEN)
        )
    finally:
        db_gen.close()
    assert row is None


def test_remove_device_not_found_returns_404(client: TestClient) -> None:
    token = register_and_login(client)

    response = client.delete(
        f"/users/me/devices/{VALID_TOKEN}", headers=auth_headers(token)
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Device not found"


def test_remove_device_of_another_user_returns_404(client: TestClient) -> None:
    token_a = register_and_login(client, "device_owner@hangy.com")
    token_b = register_and_login(client, "device_intruder@hangy.com")
    client.post(
        "/users/me/devices",
        json={"device_token": VALID_TOKEN, "platform": "ANDROID"},
        headers=auth_headers(token_a),
    )

    response = client.delete(
        f"/users/me/devices/{VALID_TOKEN}", headers=auth_headers(token_b)
    )
    assert response.status_code == 404


def test_remove_device_unauthenticated_returns_401(client: TestClient) -> None:
    response = client.delete(f"/users/me/devices/{VALID_TOKEN}")
    assert response.status_code == 401
