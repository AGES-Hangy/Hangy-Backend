from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import DeviceModel
from app.main import app

USER_EMAIL = "test_device@hangy.com"


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


def register_user(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/register",
        json={"email": USER_EMAIL, "password": "strong-password"},
    )
    assert response.status_code == 201
    user_id = response.json()["user_id"]

    login_response = client.post(
        "/login",
        data={"username": USER_EMAIL, "password": "strong-password"},
    )
    token = login_response.json()["access_token"]
    return user_id, token


def test_remove_device_on_logout(client: TestClient) -> None:
    user_id_str, token = register_user(client)
    user_id = UUID(user_id_str)

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        device = DeviceModel(device_token="expo-token-123", user_id=user_id)
        db.add(device)
        db.commit()
    finally:
        db_generator.close()

    response = client.delete(
        "/users/me/devices/expo-token-123",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        device_in_db = db.scalar(
            select(DeviceModel).where(DeviceModel.device_token == "expo-token-123")
        )
    finally:
        db_generator.close()

    assert device_in_db is None


def test_remove_device_not_found(client: TestClient) -> None:
    _, token = register_user(client)

    response = client.delete(
        "/users/me/devices/expo-token-123",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Device not found"
