"""Tests for GET /users/me/connections/pending.

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
from app.domain.enums import UserConnectionStatusEnum, UserRoleEnum, UserTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    UserBlockModel,
    UserConnectionModel,
    UserModel,
)
from app.main import app

URL = "/users/me/connections/pending"
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def pending_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


def create_user(
    db: Session,
    name: str = "Test User",
    photo_url: str | None = None,
    user_id: UUID | None = None,
) -> UserModel:
    user = UserModel(
        user_id=user_id or uuid4(),
        user_type=UserTypeEnum.PERSONAL,
        role=UserRoleEnum.USER,
        email=f"{uuid4()}@test.com",
        password_hash="hashed",
        name=name,
        profile_photo_url=photo_url,
    )
    db.add(user)
    db.flush()
    return user


def add_connection(
    db: Session,
    requester: UserModel,
    receiver: UserModel,
    *,
    status: UserConnectionStatusEnum = UserConnectionStatusEnum.PENDING,
    created_at: datetime = NOW,
    deleted_at: datetime | None = None,
    connection_id: UUID | None = None,
) -> UserConnectionModel:
    connection = UserConnectionModel(
        connection_id=connection_id or uuid4(),
        requester_id=requester.user_id,
        receiver_id=receiver.user_id,
        status=status,
        created_at=created_at,
        deleted_at=deleted_at,
    )
    db.add(connection)
    db.flush()
    return connection


def requester_names(response) -> list[str]:
    assert response.status_code == 200
    return [item["user"]["name"] for item in response.json()["items"]]


def test_item_has_the_documented_shape_with_the_requester_as_user(
    pending_client,
) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        bruno = create_user(db, "Bruno Lima", "https://img/bruno.jpg")
        connection = add_connection(db, bruno, me)
        db.commit()
        headers = make_token(me.user_id)
        expected = {
            "items": [
                {
                    "connection_id": str(connection.connection_id),
                    "user": {
                        "id": str(bruno.user_id),
                        "name": "Bruno Lima",
                        "photo_url": "https://img/bruno.jpg",
                    },
                    "created_at": NOW.replace(tzinfo=None).isoformat(),
                }
            ],
            "next_cursor": None,
        }

    response = client.get(URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == expected


def test_requests_sent_by_me_are_left_out(pending_client) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        add_connection(db, me, ana)
        add_connection(db, bruno, me)
        db.commit()
        headers = make_token(me.user_id)

    assert requester_names(client.get(URL, headers=headers)) == ["Bruno"]


def test_requests_between_other_users_are_left_out(pending_client) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        add_connection(db, ana, bruno)
        db.commit()
        headers = make_token(me.user_id)

    assert requester_names(client.get(URL, headers=headers)) == []


@pytest.mark.parametrize(
    "status",
    [UserConnectionStatusEnum.CONFIRMED, UserConnectionStatusEnum.REJECTED],
)
def test_answered_requests_are_left_out(
    pending_client, status: UserConnectionStatusEnum
) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        ana = create_user(db, "Ana")
        add_connection(db, ana, me, status=status)
        db.commit()
        headers = make_token(me.user_id)

    assert requester_names(client.get(URL, headers=headers)) == []


def test_undone_request_is_left_out(pending_client) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        ana = create_user(db, "Ana")
        add_connection(db, ana, me, deleted_at=NOW)
        db.commit()
        headers = make_token(me.user_id)

    assert requester_names(client.get(URL, headers=headers)) == []


def test_request_from_deleted_account_is_left_out(pending_client) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        ana = create_user(db, "Ana")
        ana.deleted_at = NOW
        add_connection(db, ana, me)
        db.commit()
        headers = make_token(me.user_id)

    assert requester_names(client.get(URL, headers=headers)) == []


@pytest.mark.parametrize("i_blocked", [True, False])
def test_request_with_a_block_in_either_direction_is_left_out(
    pending_client, i_blocked: bool
) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        ana = create_user(db, "Ana")
        bruno = create_user(db, "Bruno")
        add_connection(db, ana, me)
        add_connection(db, bruno, me)
        blocker, blocked = (me, ana) if i_blocked else (ana, me)
        db.add(UserBlockModel(blocker_id=blocker.user_id, blocked_id=blocked.user_id))
        db.commit()
        headers = make_token(me.user_id)

    assert requester_names(client.get(URL, headers=headers)) == ["Bruno"]


def test_requests_are_ordered_newest_first_regardless_of_id_order(
    pending_client,
) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        ids = sorted(uuid4() for _ in range(3))
        for index, connection_id in enumerate(ids):
            requester = create_user(db, f"User {index}")
            add_connection(
                db,
                requester,
                me,
                created_at=NOW - timedelta(days=3 - index),
                connection_id=connection_id,
            )
        db.commit()
        headers = make_token(me.user_id)

    assert requester_names(client.get(URL, headers=headers)) == [
        "User 2",
        "User 1",
        "User 0",
    ]


def test_pagination_walks_every_request_once_even_with_equal_dates(
    pending_client,
) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        expected: set[str] = set()
        for index in range(7):
            requester = create_user(db, f"User {index}")
            connection = add_connection(
                db, requester, me, created_at=NOW - timedelta(hours=index // 2)
            )
            expected.add(str(connection.connection_id))
        db.commit()
        headers = make_token(me.user_id)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = client.get(URL, params=params, headers=headers).json()
        seen += [item["connection_id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == 7
    assert set(seen) == expected


def test_exact_page_size_returns_no_next_cursor(pending_client) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        for index in range(2):
            requester = create_user(db, f"User {index}")
            add_connection(db, requester, me, created_at=NOW - timedelta(hours=index))
        db.commit()
        headers = make_token(me.user_id)

    body = client.get(URL, params={"limit": 2}, headers=headers).json()

    assert len(body["items"]) == 2
    assert body["next_cursor"] is None


def test_default_page_size_is_20(pending_client) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        for index in range(21):
            requester = create_user(db, f"User {index}")
            add_connection(db, requester, me, created_at=NOW - timedelta(minutes=index))
        db.commit()
        headers = make_token(me.user_id)

    body = client.get(URL, headers=headers).json()

    assert len(body["items"]) == 20
    assert body["next_cursor"] is not None


def test_empty_cursor_is_treated_as_first_page(pending_client) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        ana = create_user(db, "Ana")
        add_connection(db, ana, me)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params={"limit": 20, "cursor": ""}, headers=headers)

    assert requester_names(response) == ["Ana"]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"limit": "abc"},
        {"cursor": "not-a-valid-cursor"},
    ],
)
def test_invalid_pagination_returns_400(pending_client, params: dict) -> None:
    client, session = pending_client
    with session() as db:
        me = create_user(db, "Me")
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params=params, headers=headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_missing_token_returns_401(pending_client) -> None:
    client, _ = pending_client

    response = client.get(URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_invalid_token_returns_401(pending_client) -> None:
    client, _ = pending_client

    response = client.get(URL, headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
