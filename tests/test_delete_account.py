import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import EventPrivacyEnum, EventStatusEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.person_profile_model import PersonProfileModel
from app.main import app

TERMS_VERSION = "2026-08-01"
USER_EMAIL = "delete_me@hangy.com"
USER_PASSWORD = "senha-forte-123"

PERSONAL_PAYLOAD = {
    "user_type": "PERSONAL",
    "email": USER_EMAIL,
    "password": USER_PASSWORD,
    "name": "Delete Me",
    "cpf": "52998224725",
    "phone": "51999990000",
    "date_of_birth": "2000-04-12",
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
    with testing_session() as db, TestClient(app) as test_client:
        test_client.db = db  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def register_and_login(client: TestClient) -> tuple[str, str]:
    reg = client.post("/auth/register", json=PERSONAL_PAYLOAD)
    assert reg.status_code == 201
    user_id = reg.json()["user"]["id"]

    login = client.post(
        "/auth/login",
        json={"email": USER_EMAIL, "password": USER_PASSWORD},
    )
    assert login.status_code == 200
    return login.json()["access_token"], user_id


def _delete_me(client: TestClient, token: str, password: str):
    return client.request(
        "DELETE",
        "/users/me",
        content=json.dumps({"password": password}),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )


def test_delete_account_returns_204_and_sets_deleted_at(client: TestClient) -> None:
    token, _ = register_and_login(client)

    response = _delete_me(client, token, USER_PASSWORD)

    assert response.status_code == 204
    assert response.content == b""

    db: Session = client.db  # type: ignore[attr-defined]
    db.expire_all()
    user = db.scalar(select(UserModel).where(UserModel.email.like("deleted_%")))
    assert user is not None
    assert user.deleted_at is not None


def test_delete_account_wrong_password_returns_403_and_does_not_delete(
    client: TestClient,
) -> None:
    token, _ = register_and_login(client)

    response = _delete_me(client, token, "wrong-password")

    assert response.status_code == 403
    assert response.json() == {"detail": "Password confirmation failed"}

    db: Session = client.db  # type: ignore[attr-defined]
    db.expire_all()
    user = db.scalar(select(UserModel).where(UserModel.email == USER_EMAIL))
    assert user is not None
    assert user.deleted_at is None


def test_token_rejected_after_account_deleted(client: TestClient) -> None:
    token, _ = register_and_login(client)

    delete_response = _delete_me(client, token, USER_PASSWORD)
    assert delete_response.status_code == 204

    me_response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 403
    assert me_response.json() == {"detail": "Account has been deleted"}


def test_login_rejected_after_deletion(client: TestClient) -> None:
    token, _ = register_and_login(client)

    delete_response = _delete_me(client, token, USER_PASSWORD)
    assert delete_response.status_code == 204

    login_response = client.post(
        "/auth/login",
        json={"email": USER_EMAIL, "password": USER_PASSWORD},
    )
    assert login_response.status_code == 401


def test_pii_fields_anonymized_after_deletion(client: TestClient) -> None:
    token, _ = register_and_login(client)

    delete_response = _delete_me(client, token, USER_PASSWORD)
    assert delete_response.status_code == 204

    db: Session = client.db  # type: ignore[attr-defined]
    db.expire_all()

    user = db.scalar(select(UserModel).where(UserModel.email.like("deleted_%")))
    assert user is not None
    assert user.name is None
    assert user.user_phone is None

    profile = db.scalar(
        select(PersonProfileModel).where(PersonProfileModel.user_id == user.user_id)
    )
    assert profile is not None
    assert profile.cpf != PERSONAL_PAYLOAD["cpf"]
    assert profile.date_of_birth is not None  # NOT NULL — uses sentinel date(1900, 1, 1)
    assert profile.state == ""
    assert profile.city == ""


def test_same_email_can_register_again_after_deletion(client: TestClient) -> None:
    token, _ = register_and_login(client)

    delete_response = _delete_me(client, token, USER_PASSWORD)
    assert delete_response.status_code == 204

    reg2 = client.post("/auth/register", json=PERSONAL_PAYLOAD)
    assert reg2.status_code == 201


def test_delete_account_with_future_event_returns_409(client: TestClient) -> None:
    token, user_id = register_and_login(client)

    db: Session = client.db  # type: ignore[attr-defined]
    future_event = EventModel(
        event_creator_id=uuid.UUID(user_id),
        event_title="Evento Futuro",
        event_latitude=-30.0,
        event_longitude=-51.0,
        starts_at=datetime.now(UTC) + timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=2),
        event_status=EventStatusEnum.PUBLISHED,
        event_privacy=EventPrivacyEnum.PUBLIC,
    )
    db.add(future_event)
    db.commit()

    response = _delete_me(client, token, USER_PASSWORD)

    assert response.status_code == 409
    assert response.json() == {"detail": "Cannot delete with active events"}


def test_past_event_does_not_block_deletion(client: TestClient) -> None:
    token, user_id = register_and_login(client)

    db: Session = client.db  # type: ignore[attr-defined]
    past_event = EventModel(
        event_creator_id=uuid.UUID(user_id),
        event_title="Evento Passado",
        event_latitude=-30.0,
        event_longitude=-51.0,
        starts_at=datetime.now(UTC) - timedelta(days=3),
        ends_at=datetime.now(UTC) - timedelta(days=1),
        event_status=EventStatusEnum.PUBLISHED,
        event_privacy=EventPrivacyEnum.PUBLIC,
    )
    db.add(past_event)
    db.commit()

    response = _delete_me(client, token, USER_PASSWORD)

    assert response.status_code == 204


def test_cancelled_event_does_not_block_deletion(client: TestClient) -> None:
    token, user_id = register_and_login(client)

    db: Session = client.db  # type: ignore[attr-defined]
    cancelled_event = EventModel(
        event_creator_id=uuid.UUID(user_id),
        event_title="Evento Cancelado",
        event_latitude=-30.0,
        event_longitude=-51.0,
        starts_at=datetime.now(UTC) + timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=2),
        event_status=EventStatusEnum.CANCELLED,
        event_privacy=EventPrivacyEnum.PUBLIC,
    )
    db.add(cancelled_event)
    db.commit()

    response = _delete_me(client, token, USER_PASSWORD)

    assert response.status_code == 204


def test_delete_without_token_returns_401(client: TestClient) -> None:
    response = client.request(
        "DELETE",
        "/users/me",
        content=json.dumps({"password": USER_PASSWORD}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401
