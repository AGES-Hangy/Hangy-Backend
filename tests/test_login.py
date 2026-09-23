from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
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


def register(client: TestClient, payload: dict) -> dict:
    response = client.post("/register", json=payload)
    assert response.status_code == 201
    return response.json()


def test_valid_login_returns_200_with_a_token_whose_sub_is_the_user_id(
    client: TestClient,
) -> None:
    registered = register(client, PERSONAL_PAYLOAD)

    response = client.post(
        "/login",
        json={
            "email": PERSONAL_PAYLOAD["email"],
            "password": PERSONAL_PAYLOAD["password"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    payload = jwt.decode(
        body["access_token"],
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload["sub"] == registered["user"]["id"]
    assert body["user"]["id"] == registered["user"]["id"]
    assert body["user"]["user_type"] == "PERSONAL"
    assert body["user"]["name"] == PERSONAL_PAYLOAD["name"]


def test_wrong_password_and_unknown_email_return_the_same_401(
    client: TestClient,
) -> None:
    register(client, PERSONAL_PAYLOAD)

    wrong_password = client.post(
        "/login",
        json={"email": PERSONAL_PAYLOAD["email"], "password": "senha-errada-999"},
    )
    unknown_email = client.post(
        "/login",
        json={"email": "ninguem@exemplo.com", "password": "qualquer-senha-123"},
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert (
        wrong_password.json()
        == unknown_email.json()
        == {"detail": "Incorrect email or password"}
    )


def test_deleted_account_returns_403(client: TestClient) -> None:
    registered = register(client, PERSONAL_PAYLOAD)

    db: Session = client.db  # type: ignore[attr-defined]
    user = db.scalar(
        select(UserModel).where(UserModel.email == PERSONAL_PAYLOAD["email"])
    )
    assert user is not None
    user.deleted_at = datetime.now(UTC)
    db.commit()

    response = client.post(
        "/login",
        json={
            "email": PERSONAL_PAYLOAD["email"],
            "password": PERSONAL_PAYLOAD["password"],
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Account has been deleted"}
    assert registered["user"]["id"] == str(user.user_id)


def test_invalid_email_format_returns_422(client: TestClient) -> None:
    response = client.post(
        "/login",
        json={"email": "not-an-email", "password": "senha-forte-123"},
    )

    assert response.status_code == 422


def test_users_me_returns_the_right_user_type_for_personal_and_business(
    client: TestClient,
) -> None:
    register(client, PERSONAL_PAYLOAD)
    register(client, BUSINESS_PAYLOAD)

    personal_login = client.post(
        "/login",
        json={
            "email": PERSONAL_PAYLOAD["email"],
            "password": PERSONAL_PAYLOAD["password"],
        },
    )
    business_login = client.post(
        "/login",
        json={
            "email": BUSINESS_PAYLOAD["email"],
            "password": BUSINESS_PAYLOAD["password"],
        },
    )

    personal_me = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {personal_login.json()['access_token']}"},
    )
    business_me = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {business_login.json()['access_token']}"},
    )

    assert personal_me.status_code == 200
    assert personal_me.json()["user_type"] == "PERSONAL"
    assert personal_me.json()["email"] == PERSONAL_PAYLOAD["email"]

    assert business_me.status_code == 200
    assert business_me.json()["user_type"] == "BUSINESS"
    assert business_me.json()["email"] == BUSINESS_PAYLOAD["email"]


def test_token_issued_before_a_password_change_is_rejected_with_401(
    client: TestClient,
) -> None:
    registered = register(client, PERSONAL_PAYLOAD)
    login_response = client.post(
        "/login",
        json={
            "email": PERSONAL_PAYLOAD["email"],
            "password": PERSONAL_PAYLOAD["password"],
        },
    )
    token = login_response.json()["access_token"]

    me_before = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_before.status_code == 200

    db: Session = client.db  # type: ignore[attr-defined]
    user = db.scalar(
        select(UserModel).where(UserModel.email == PERSONAL_PAYLOAD["email"])
    )
    assert user is not None
    assert str(user.user_id) == registered["user"]["id"]
    user.password_changed_at = datetime.now(UTC) + timedelta(minutes=5)
    db.commit()

    me_after = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})

    assert me_after.status_code == 401
