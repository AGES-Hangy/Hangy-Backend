from collections.abc import Iterator

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


def register_user(client: TestClient) -> None:
    response = client.post(
        "/register",
        json={"username": "felipe", "password": "strong-password"},
    )
    assert response.status_code == 201


def test_register_persists_a_hashed_password(client: TestClient) -> None:
    register_user(client)

    response = client.get("/users/me", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        user = db.scalar(select(UserModel).where(UserModel.username == "felipe"))
    finally:
        db_generator.close()

    assert user is not None
    assert user.password_hash != "strong-password"


def test_register_rejects_a_duplicate_username(client: TestClient) -> None:
    register_user(client)

    response = client.post(
        "/register",
        json={"username": "felipe", "password": "another-password"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Username is already registered"}


def test_login_returns_a_jwt_and_token_authenticates_user(
    client: TestClient,
) -> None:
    register_user(client)

    login_response = client.post(
        "/login",
        data={"username": "felipe", "password": "strong-password"},
    )

    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    assert login_response.json()["token_type"] == "bearer"
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert payload["sub"] == "felipe"
    assert "exp" in payload

    me_response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "felipe"


def test_login_rejects_an_invalid_password(client: TestClient) -> None:
    register_user(client)

    response = client.post(
        "/login",
        data={"username": "felipe", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_openapi_offers_oauth2_and_direct_bearer_authentication(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    security_schemes = schema["components"]["securitySchemes"]

    assert security_schemes["OAuth2Password"]["type"] == "oauth2"
    assert security_schemes["BearerToken"] == {
        "type": "http",
        "description": "Paste an existing JWT access token.",
        "scheme": "bearer",
    }
    assert schema["paths"]["/users/me"]["get"]["security"] == [
        {"OAuth2Password": []},
        {"BearerToken": []},
    ]
