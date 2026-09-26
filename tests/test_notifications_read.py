import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import NotificationTypeEnum, UserTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import NotificationModel, UserModel
from app.main import app

USER_EMAIL = "felipe@hangy.com"
USER_PASSWORD = "strong-password"
UNREAD_COUNT_URL = "/notifications/unread-count"
CREDENTIALS_ERROR = {"detail": "Could not validate credentials"}


def read_url(notification_id: uuid.UUID) -> str:
    return f"/notifications/{notification_id}/read"


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
            json={
                "user_type": "PERSONAL",
                "email": USER_EMAIL,
                "password": USER_PASSWORD,
                "name": "Felipe",
                "cpf": "52998224725",
                "date_of_birth": "2000-04-12",
                "country": "BR",
                "state": "RS",
                "city": "Porto Alegre",
                "accepted_terms_version": "2026-08-01",
            },
        )
        assert register.status_code == 201
        login = client.post(
            "/login",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert login.status_code == 200
        yield NotificationContext(
            client=client,
            db=db,
            token=login.json()["access_token"],
            user_id=uuid.UUID(register.json()["user"]["id"]),
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


def create_notification(
    db: Session, user_id: uuid.UUID, read: bool = False
) -> uuid.UUID:
    notification = NotificationModel(
        user_id=user_id,
        type=NotificationTypeEnum.EVENT_UPDATED,
        read=read,
    )
    db.add(notification)
    db.commit()
    return notification.notification_id


def is_read(db: Session, notification_id: uuid.UUID) -> bool:
    # The request ran in another session, so drop what this one cached.
    db.expire_all()
    return db.get(NotificationModel, notification_id).read


def unread_count(context: NotificationContext) -> int:
    response = context.client.get(UNREAD_COUNT_URL, headers=context.auth_headers)
    assert response.status_code == 200
    return response.json()["unread_count"]


def test_owner_marks_the_notification_as_read(context: NotificationContext) -> None:
    notification_id = create_notification(context.db, context.user_id)

    response = context.client.patch(
        read_url(notification_id), headers=context.auth_headers
    )

    assert response.status_code == 204
    assert response.content == b""
    assert is_read(context.db, notification_id)


def test_marking_an_already_read_notification_is_idempotent(
    context: NotificationContext,
) -> None:
    notification_id = create_notification(context.db, context.user_id)

    first = context.client.patch(
        read_url(notification_id), headers=context.auth_headers
    )
    second = context.client.patch(
        read_url(notification_id), headers=context.auth_headers
    )

    assert first.status_code == 204
    assert second.status_code == 204
    assert is_read(context.db, notification_id)


def test_marking_another_users_notification_is_forbidden(
    context: NotificationContext,
) -> None:
    other_user_id = create_user(context.db, "ana@hangy.com")
    notification_id = create_notification(context.db, other_user_id)

    response = context.client.patch(
        read_url(notification_id), headers=context.auth_headers
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Not your notification"}
    assert not is_read(context.db, notification_id)


def test_marking_an_unknown_notification_is_not_found(
    context: NotificationContext,
) -> None:
    response = context.client.patch(
        read_url(uuid.uuid4()), headers=context.auth_headers
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Notification not found"}


def test_marking_as_read_requires_a_token(context: NotificationContext) -> None:
    notification_id = create_notification(context.db, context.user_id)

    response = context.client.patch(read_url(notification_id))

    assert response.status_code == 401
    assert response.json() == CREDENTIALS_ERROR
    assert not is_read(context.db, notification_id)


def test_marking_as_read_rejects_an_invalid_token(
    context: NotificationContext,
) -> None:
    notification_id = create_notification(context.db, context.user_id)

    response = context.client.patch(
        read_url(notification_id), headers={"Authorization": "Bearer invalid"}
    )

    assert response.status_code == 401
    assert response.json() == CREDENTIALS_ERROR
    assert not is_read(context.db, notification_id)


def test_marking_as_read_decrements_the_unread_count(
    context: NotificationContext,
) -> None:
    notification_id = create_notification(context.db, context.user_id)
    create_notification(context.db, context.user_id)
    assert unread_count(context) == 2

    context.client.patch(read_url(notification_id), headers=context.auth_headers)
    assert unread_count(context) == 1

    context.client.patch(read_url(notification_id), headers=context.auth_headers)
    assert unread_count(context) == 1


def test_openapi_documents_the_mark_as_read_endpoint(
    context: NotificationContext,
) -> None:
    operation = context.client.get("/openapi.json").json()["paths"][
        "/notifications/{notification_id}/read"
    ]["patch"]

    assert set(operation["responses"]) >= {"204", "401", "403", "404"}
    assert "content" not in operation["responses"]["204"]
    assert "requestBody" not in operation
