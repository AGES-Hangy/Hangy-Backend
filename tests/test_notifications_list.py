"""Tests for GET /notifications and related PATCH endpoints.

Follows the pattern from tests/test_auth.py:
- SQLite in-memory with StaticPool
- Manually minted JWTs to avoid round-tripping /register
"""

from __future__ import annotations

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
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    UserConnectionStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    ConnectionNotificationModel,
    EventCancelledNotificationModel,
    EventParticipantNotificationModel,
    NotificationModel,
    UserModel,
)
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.event_participant_model import (
    EventParticipantModel,
)
from app.infrastructure.repository.models.user_connection_model import (
    UserConnectionModel,
)
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def notif_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_token(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=30)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def create_user(db: Session, *, name: str = "Test User") -> UserModel:
    user = UserModel(
        user_id=uuid4(),
        user_type=UserTypeEnum.PERSONAL,
        role=UserRoleEnum.USER,
        email=f"{uuid4()}@test.com",
        password_hash="hashed",
        name=name,
    )
    db.add(user)
    db.flush()
    return user


def create_event(db: Session, creator_id: UUID) -> EventModel:
    event = EventModel(
        event_id=uuid4(),
        event_creator_id=creator_id,
        event_title="Test Event",
        event_latitude=0.0,
        event_longitude=0.0,
        starts_at=datetime.now(UTC) + timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=1, hours=2),
        event_status=EventStatusEnum.PUBLISHED,
        event_privacy=EventPrivacyEnum.PUBLIC,
    )
    db.add(event)
    db.flush()
    return event


def add_connection_notification(
    db: Session,
    recipient: UserModel,
    sender: UserModel,
    n_type: NotificationTypeEnum = NotificationTypeEnum.CONNECTION_REQUEST,
    *,
    read: bool = False,
    created_at: datetime | None = None,
) -> NotificationModel:
    notif = NotificationModel(
        notification_id=uuid4(),
        user_id=recipient.user_id,
        type=n_type,
        read=read,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(notif)
    db.flush()
    conn = UserConnectionModel(
        connection_id=uuid4(),
        requester_id=sender.user_id,
        receiver_id=recipient.user_id,
        status=UserConnectionStatusEnum.PENDING,
    )
    db.add(conn)
    db.flush()
    db.add(
        ConnectionNotificationModel(
            notification_id=notif.notification_id,
            connection_id=conn.connection_id,
        )
    )
    db.flush()
    return notif


def add_participant_notification(
    db: Session,
    recipient: UserModel,
    sender: UserModel,
    event: EventModel,
    n_type: NotificationTypeEnum = NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
    *,
    read: bool = False,
    created_at: datetime | None = None,
) -> NotificationModel:
    notif = NotificationModel(
        notification_id=uuid4(),
        user_id=recipient.user_id,
        type=n_type,
        read=read,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(notif)
    db.flush()
    participant = EventParticipantModel(
        participant_id=uuid4(),
        user_id=sender.user_id,
        event_id=event.event_id,
        status=EventParticipantStatusEnum.PENDING,
    )
    db.add(participant)
    db.flush()
    db.add(
        EventParticipantNotificationModel(
            notification_id=notif.notification_id,
            participant_id=participant.participant_id,
        )
    )
    db.flush()
    return notif


def add_cancelled_notification(
    db: Session,
    recipient: UserModel,
    event: EventModel,
    *,
    read: bool = False,
    created_at: datetime | None = None,
) -> NotificationModel:
    notif = NotificationModel(
        notification_id=uuid4(),
        user_id=recipient.user_id,
        type=NotificationTypeEnum.EVENT_CANCELLED,
        read=read,
        created_at=created_at or datetime.now(UTC),
    )
    db.add(notif)
    db.flush()
    db.add(
        EventCancelledNotificationModel(
            notification_id=notif.notification_id,
            event_id=event.event_id,
        )
    )
    db.flush()
    return notif


# ---------------------------------------------------------------------------
# Tests — list endpoint
# ---------------------------------------------------------------------------


def test_list_returns_chronological_desc(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        sender = create_user(db)
        t1 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
        t2 = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)
        t3 = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
        add_connection_notification(db, user, sender, created_at=t1)
        add_connection_notification(db, user, sender, created_at=t3)
        add_connection_notification(db, user, sender, created_at=t2)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/notifications", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 3
    dates = [i["created_at"] for i in items]
    assert dates == sorted(dates, reverse=True), "Items must be newest-first"


def test_connection_notification_payload(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        sender = create_user(db, name="Ana Sender")
        add_connection_notification(
            db, user, sender, NotificationTypeEnum.CONNECTION_REQUEST
        )
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/notifications", headers=headers)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["type"] == "CONNECTION_REQUEST"
    assert "connection_id" in item["payload"]
    assert item["payload"]["sender"]["name"] == "Ana Sender"


def test_participant_notification_payload(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        owner = create_user(db)
        requester = create_user(db, name="Bob Requester")
        event = create_event(db, owner.user_id)
        add_participant_notification(
            db,
            owner,
            requester,
            event,
            NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
        )
        db.commit()
        headers = make_token(owner.user_id)

    resp = client.get("/notifications", headers=headers)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["type"] == "EVENT_PARTICIPATION_REQUEST"
    assert item["payload"]["event_title"] == "Test Event"
    assert item["payload"]["sender"]["name"] == "Bob Requester"


def test_cancelled_notification_payload(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        creator = create_user(db)
        event = create_event(db, creator.user_id)
        add_cancelled_notification(db, user, event)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/notifications", headers=headers)
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["type"] == "EVENT_CANCELLED"
    assert item["payload"]["event_title"] == "Test Event"


def test_unread_only_filter(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        sender = create_user(db)
        add_connection_notification(db, user, sender, read=True)
        add_connection_notification(db, user, sender, read=False)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/notifications?unread_only=true", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["read"] is False


def test_unread_count_in_response(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        sender = create_user(db)
        add_connection_notification(db, user, sender, read=True)
        add_connection_notification(db, user, sender, read=False)
        add_connection_notification(db, user, sender, read=False)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/notifications", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["unread_count"] == 2


def test_pagination_cursor(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        sender = create_user(db)
        for i in range(5):
            add_connection_notification(
                db,
                user,
                sender,
                created_at=datetime(2026, 8, i + 1, tzinfo=UTC),
            )
        db.commit()
        headers = make_token(user.user_id)

    # First page
    resp1 = client.get("/notifications?limit=3", headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["items"]) == 3
    assert data1["next_cursor"] is not None

    # Second page
    resp2 = client.get(
        f"/notifications?limit=3&cursor={data1['next_cursor']}", headers=headers
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["items"]) == 2
    assert data2["next_cursor"] is None

    # Combined IDs must be 5 unique items
    all_ids = {i["notification_id"] for i in data1["items"] + data2["items"]}
    assert len(all_ids) == 5


def test_invalid_limit_returns_400(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/notifications?limit=0", headers=headers)
    assert resp.status_code == 422  # FastAPI validates ge=1 before service


def test_invalid_cursor_returns_400(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/notifications?cursor=not-a-valid-cursor!!", headers=headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid pagination parameters"


# ---------------------------------------------------------------------------
# Tests — mark as read
# ---------------------------------------------------------------------------


def test_mark_as_read_decrements_unread_count(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        sender = create_user(db)
        notif = add_connection_notification(db, user, sender, read=False)
        db.commit()
        notif_id = str(notif.notification_id)
        headers = make_token(user.user_id)

    # Before
    resp = client.get("/notifications", headers=headers)
    assert resp.json()["unread_count"] == 1

    # Mark as read
    patch = client.patch(f"/notifications/{notif_id}/read", headers=headers)
    assert patch.status_code == 204

    # After
    resp2 = client.get("/notifications", headers=headers)
    assert resp2.json()["unread_count"] == 0


def test_mark_all_as_read_zeroes_counter(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user = create_user(db)
        sender = create_user(db)
        add_connection_notification(db, user, sender, read=False)
        add_connection_notification(db, user, sender, read=False)
        db.commit()
        headers = make_token(user.user_id)

    assert client.get("/notifications", headers=headers).json()["unread_count"] == 2

    patch = client.patch("/notifications/read-all", headers=headers)
    assert patch.status_code == 204

    assert client.get("/notifications", headers=headers).json()["unread_count"] == 0


def test_mark_other_user_notification_returns_403(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = notif_client
    with session_factory() as db:
        user_a = create_user(db)
        user_b = create_user(db)
        sender = create_user(db)
        notif = add_connection_notification(db, user_a, sender, read=False)
        db.commit()
        notif_id = str(notif.notification_id)
        headers_b = make_token(user_b.user_id)

    resp = client.patch(f"/notifications/{notif_id}/read", headers=headers_b)
    assert resp.status_code == 403


def test_unauthenticated_request_returns_401(
    notif_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = notif_client
    resp = client.get("/notifications")
    assert resp.status_code == 401
