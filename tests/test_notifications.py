from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import NotificationTypeEnum, UserRoleEnum, UserTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import NotificationModel, UserModel
from app.main import app

USER_A_ID = UUID("0f000010-0000-4000-8000-000000000001")
USER_B_ID = UUID("0f000010-0000-4000-8000-000000000002")


@pytest.fixture
def notifications_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        db.add_all(
            [
                UserModel(
                    user_id=USER_A_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="user_a@notifications.test",
                    password_hash="hash",
                    name="User A",
                ),
                UserModel(
                    user_id=USER_B_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="user_b@notifications.test",
                    password_hash="hash",
                    name="User B",
                ),
            ]
        )
        db.commit()

    def override_get_db() -> Iterator[Session]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _token_for(user_id: UUID) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def test_mark_all_as_read_zeroes_unread_count(
    notifications_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notifications_client

    with session_factory() as db:
        db.add_all(
            [
                NotificationModel(
                    notification_id=uuid4(),
                    user_id=USER_A_ID,
                    type=NotificationTypeEnum.CONNECTION_REQUEST,
                    read=False,
                ),
                NotificationModel(
                    notification_id=uuid4(),
                    user_id=USER_A_ID,
                    type=NotificationTypeEnum.EVENT_UPDATED,
                    read=False,
                ),
            ]
        )
        db.commit()

    response = client.patch(
        "/notifications/read-all",
        headers={"Authorization": f"Bearer {_token_for(USER_A_ID)}"},
    )

    assert response.status_code == 204
    assert response.content == b""

    with session_factory() as db:
        unread_count = (
            db.query(NotificationModel)
            .filter(
                NotificationModel.user_id == USER_A_ID,
                NotificationModel.read.is_(False),
            )
            .count()
        )
        assert unread_count == 0

        read_count = (
            db.query(NotificationModel)
            .filter(
                NotificationModel.user_id == USER_A_ID,
                NotificationModel.read.is_(True),
            )
            .count()
        )
        assert read_count == 2


def test_mark_all_as_read_does_not_touch_other_users(
    notifications_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notifications_client

    other_notification_id = uuid4()
    with session_factory() as db:
        db.add_all(
            [
                NotificationModel(
                    notification_id=uuid4(),
                    user_id=USER_A_ID,
                    type=NotificationTypeEnum.CONNECTION_REQUEST,
                    read=False,
                ),
                NotificationModel(
                    notification_id=other_notification_id,
                    user_id=USER_B_ID,
                    type=NotificationTypeEnum.CONNECTION_REQUEST,
                    read=False,
                ),
            ]
        )
        db.commit()

    response = client.patch(
        "/notifications/read-all",
        headers={"Authorization": f"Bearer {_token_for(USER_A_ID)}"},
    )

    assert response.status_code == 204

    with session_factory() as db:
        other_notification = db.get(NotificationModel, other_notification_id)
        assert other_notification is not None
        assert other_notification.read is False


def test_mark_all_as_read_requires_authentication(
    notifications_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = notifications_client

    response = client.patch("/notifications/read-all")

    assert response.status_code == 401


def test_mark_all_as_read_is_idempotent_with_no_notifications(
    notifications_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = notifications_client

    response = client.patch(
        "/notifications/read-all",
        headers={"Authorization": f"Bearer {_token_for(USER_A_ID)}"},
    )

    assert response.status_code == 204
