from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserModel
from app.main import app

TERMS_VERSION = "2026-08-01"

PERSONAL_PAYLOAD = {
    "user_type": "PERSONAL",
    "email": "ana@exemplo.com",
    "password": "senha-forte-123",
    "name": "Ana Souza",
    "cpf": "52998224725",
    "phone": "51999990000",
    "date_of_birth": "2000-04-12",
    "country": "BR",
    "state": "RS",
    "city": "Porto Alegre",
    "accepted_terms_version": TERMS_VERSION,
}

BUSINESS_PAYLOAD = {
    "user_type": "BUSINESS",
    "email": "contato@bar.com",
    "password": "senha-forte-123",
    "business_name": "Bar do Zé",
    "cnpj": "11222333000181",
    "phone": "5133330000",
    "description": "Bar e petiscaria",
    "location": {"latitude": -30.0331, "longitude": -51.23},
    "address": "Av. Independência, 100 — Porto Alegre",
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
    with testing_session() as db, TestClient(app) as test_client:
        test_client.db = db  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def register_and_login(client: TestClient, payload: dict) -> str:
    register_response = client.post("/register", json=payload)
    assert register_response.status_code == 201

    login_response = client.post(
        "/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def test_read_current_user_returns_personal_profile_shape(
    client: TestClient,
) -> None:
    token = register_and_login(client, PERSONAL_PAYLOAD)

    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert "user_id" not in body
    assert "role" not in body
    assert body["email"] == PERSONAL_PAYLOAD["email"]
    assert body["user_type"] == "PERSONAL"
    assert body["name"] == PERSONAL_PAYLOAD["name"]
    assert body["profile"] == {
        "date_of_birth": PERSONAL_PAYLOAD["date_of_birth"],
        "city": PERSONAL_PAYLOAD["city"],
        "state": PERSONAL_PAYLOAD["state"],
        "photo_url": None,
    }


def test_read_current_user_returns_business_profile_shape(
    client: TestClient,
) -> None:
    token = register_and_login(client, BUSINESS_PAYLOAD)

    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["user_type"] == "BUSINESS"
    assert body["name"] == BUSINESS_PAYLOAD["business_name"]
    assert body["profile"] == {
        "cnpj": BUSINESS_PAYLOAD["cnpj"],
        "address": BUSINESS_PAYLOAD["address"],
        "latitude": BUSINESS_PAYLOAD["location"]["latitude"],
        "longitude": BUSINESS_PAYLOAD["location"]["longitude"],
        "photo_url": None,
    }


def test_read_current_user_rejects_deleted_account_with_a_still_valid_token(
    client: TestClient,
) -> None:
    token = register_and_login(client, PERSONAL_PAYLOAD)

    db: Session = client.db  # type: ignore[attr-defined]
    user = db.scalar(
        select(UserModel).where(UserModel.email == PERSONAL_PAYLOAD["email"])
    )
    assert user is not None
    user.deleted_at = datetime.now(UTC)
    db.commit()

    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Account has been deleted"}
