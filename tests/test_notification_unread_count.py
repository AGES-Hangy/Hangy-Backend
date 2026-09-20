import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import NotificationTypeEnum, UserTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import NotificationModel, UserModel
from app.main import app

USER_EMAIL = "felipe@hangy.com"
USER_PASSWORD = "strong-password"
UNREAD_COUNT_URL = "/notifications/unread-count"
CREDENTIALS_ERROR = {"detail": "Could not validate credentials"}


@dataclass(frozen=True)
class NotificationContext:
    client: TestClient
    db: Session
    token: str
    user_id: uuid.UUID

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def context() -> Iterator[NotificationContext]:
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
    with testing_session() as db, TestClient(app) as client:
        register = client.post(
            "/register",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert register.status_code == 201
        login = client.post(
            "/login",
            data={"username": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert login.status_code == 200
        yield NotificationContext(
            client=client,
            db=db,
            token=login.json()["access_token"],
            user_id=uuid.UUID(register.json()["user_id"]),
        )
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_user(db: Session, email: str) -> uuid.UUID:
    user = UserModel(
        user_type=UserTypeEnum.PERSONAL,
        email=email,
        password_hash="hashed",
    )
    db.add(user)
    db.commit()
    return user.user_id


def create_notifications(
    db: Session, user_id: uuid.UUID, unread: int = 0, read: int = 0
) -> None:
    db.add_all(
        NotificationModel(
            user_id=user_id,
            type=NotificationTypeEnum.EVENT_UPDATED,
            read=is_read,
        )
        for is_read, amount in ((False, unread), (True, read))
        for _ in range(amount)
    )
    db.commit()


def test_unread_count_returns_the_users_unread_notifications(
    context: NotificationContext,
) -> None:
    create_notifications(context.db, context.user_id, unread=3)

    response = context.client.get(UNREAD_COUNT_URL, headers=context.auth_headers)

    assert response.status_code == 200
    assert response.json() == {"unread_count": 3}


def test_unread_count_ignores_other_users_notifications(
    context: NotificationContext,
) -> None:
    other_user_id = create_user(context.db, "ana@hangy.com")
    create_notifications(context.db, context.user_id, unread=2)
    create_notifications(context.db, other_user_id, unread=5)

    response = context.client.get(UNREAD_COUNT_URL, headers=context.auth_headers)

    assert response.status_code == 200
    assert response.json() == {"unread_count": 2}


def test_unread_count_excludes_read_notifications(
    context: NotificationContext,
) -> None:
    create_notifications(context.db, context.user_id, unread=1, read=4)

    response = context.client.get(UNREAD_COUNT_URL, headers=context.auth_headers)

    assert response.status_code == 200
    assert response.json() == {"unread_count": 1}


def test_unread_count_is_zero_without_notifications(
    context: NotificationContext,
) -> None:
    response = context.client.get(UNREAD_COUNT_URL, headers=context.auth_headers)

    assert response.status_code == 200
    assert response.json() == {"unread_count": 0}


def test_unread_count_requires_a_token(context: NotificationContext) -> None:
    response = context.client.get(UNREAD_COUNT_URL)

    assert response.status_code == 401
    assert response.json() == CREDENTIALS_ERROR


def test_unread_count_rejects_an_invalid_token(context: NotificationContext) -> None:
    response = context.client.get(
        UNREAD_COUNT_URL, headers={"Authorization": "Bearer invalid"}
    )

    assert response.status_code == 401
    assert response.json() == CREDENTIALS_ERROR


def test_unread_count_rejects_an_expired_token(context: NotificationContext) -> None:
    expired_token = jwt.encode(
        {"sub": str(context.user_id), "exp": 1},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = context.client.get(
        UNREAD_COUNT_URL, headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert response.status_code == 401
    assert response.json() == CREDENTIALS_ERROR


def test_openapi_documents_the_unread_count_endpoint(
    context: NotificationContext,
) -> None:
    operation = context.client.get("/openapi.json").json()["paths"][UNREAD_COUNT_URL][
        "get"
    ]

    assert "200" in operation["responses"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UnreadNotificationCountOutput"
    }
