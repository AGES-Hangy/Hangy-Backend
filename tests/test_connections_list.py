"""Tests for GET /users/me/connections.

Follows the pattern from tests/test_notifications_list.py: SQLite in-memory
with StaticPool, manually minted JWTs, direct ORM seeding for precise
control over `updated_at` ordering and blocking rows.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
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
    PersonProfileModel,
    UserBlockModel,
    UserConnectionModel,
    UserModel,
)
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


_cpf_counter = 0


def _next_cpf() -> str:
    global _cpf_counter
    _cpf_counter += 1
    return f"{_cpf_counter:011d}"


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


def create_person_profile(
    db: Session, user_id: UUID, *, city: str = "Porto Alegre"
) -> PersonProfileModel:
    profile = PersonProfileModel(
        user_id=user_id,
        cpf=_next_cpf(),
        date_of_birth=date(2000, 1, 1),
        state="RS",
        city=city,
    )
    db.add(profile)
    db.flush()
    return profile


def create_connection(
    db: Session,
    requester: UserModel,
    receiver: UserModel,
    *,
    status: UserConnectionStatusEnum = UserConnectionStatusEnum.CONFIRMED,
    updated_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> UserConnectionModel:
    connection = UserConnectionModel(
        connection_id=uuid4(),
        requester_id=requester.user_id,
        receiver_id=receiver.user_id,
        status=status,
        deleted_at=deleted_at,
    )
    db.add(connection)
    db.flush()
    if updated_at is not None:
        connection.updated_at = updated_at
        db.flush()
    return connection


def block_user(db: Session, blocker: UserModel, blocked: UserModel) -> None:
    db.add(UserBlockModel(blocker_id=blocker.user_id, blocked_id=blocked.user_id))
    db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_returns_other_user_regardless_of_direction(
    conn_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user_a = create_user(db, name="Alice")
        user_b = create_user(db, name="Bruno")
        user_c = create_user(db, name="Carla")
        user_b_id, user_c_id = user_b.user_id, user_c.user_id
        create_person_profile(db, user_b.user_id, city="Porto Alegre")
        create_person_profile(db, user_c.user_id, city="Caxias do Sul")
        # A is the requester towards B, and the receiver from C.
        create_connection(db, user_a, user_b)
        create_connection(db, user_c, user_a)
        db.commit()
        headers = make_token(user_a.user_id)

    resp = client.get("/users/me/connections", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    user_ids = {item["user_id"] for item in body["items"]}
    assert user_ids == {str(user_b_id), str(user_c_id)}
    names = {item["name"] for item in body["items"]}
    assert names == {"Bruno", "Carla"}


def test_soft_deleted_connection_not_listed(
    conn_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user_a = create_user(db)
        user_b = create_user(db, name="Bruno")
        create_person_profile(db, user_b.user_id)
        create_connection(db, user_a, user_b, deleted_at=datetime.now(UTC))
        db.commit()
        headers = make_token(user_a.user_id)

    resp = client.get("/users/me/connections", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_pending_connection_not_listed(
    conn_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user_a = create_user(db)
        user_b = create_user(db, name="Bruno")
        create_person_profile(db, user_b.user_id)
        create_connection(db, user_a, user_b, status=UserConnectionStatusEnum.PENDING)
        db.commit()
        headers = make_token(user_a.user_id)

    resp = client.get("/users/me/connections", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_search_by_name_filters(
    conn_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user_a = create_user(db)
        bruno = create_user(db, name="Bruno Lima")
        carla = create_user(db, name="Carla Souza")
        create_person_profile(db, bruno.user_id)
        create_person_profile(db, carla.user_id)
        create_connection(db, user_a, bruno)
        create_connection(db, user_a, carla)
        db.commit()
        headers = make_token(user_a.user_id)

    resp = client.get("/users/me/connections", params={"q": "BRU"}, headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Bruno Lima"


def test_search_escapes_sql_wildcards(
    conn_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user_a = create_user(db)
        underscore_name = create_user(db, name="test_user")
        any_char_name = create_user(db, name="testXuser")
        create_person_profile(db, underscore_name.user_id)
        create_person_profile(db, any_char_name.user_id)
        create_connection(db, user_a, underscore_name)
        create_connection(db, user_a, any_char_name)
        db.commit()
        headers = make_token(user_a.user_id)

    resp = client.get(
        "/users/me/connections", params={"q": "test_user"}, headers=headers
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [item["name"] for item in items] == ["test_user"]


def test_blocked_user_not_listed(
    conn_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user_a = create_user(db)
        blocker_blocked_me = create_user(db, name="Blocked Me")
        i_blocked_them = create_user(db, name="I Blocked Them")
        create_person_profile(db, blocker_blocked_me.user_id)
        create_person_profile(db, i_blocked_them.user_id)
        create_connection(db, user_a, blocker_blocked_me)
        create_connection(db, user_a, i_blocked_them)
        block_user(db, blocker_blocked_me, user_a)
        block_user(db, user_a, i_blocked_them)
        db.commit()
        headers = make_token(user_a.user_id)

    resp = client.get("/users/me/connections", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_pagination_cursor(
    conn_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user_a = create_user(db)
        others = [create_user(db, name=f"User {i}") for i in range(5)]
        for i, other in enumerate(others):
            create_person_profile(db, other.user_id)
            create_connection(
                db,
                user_a,
                other,
                updated_at=datetime(2026, 8, i + 1, tzinfo=UTC),
            )
        db.commit()
        headers = make_token(user_a.user_id)

    resp1 = client.get("/users/me/connections", params={"limit": 3}, headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["items"]) == 3
    assert data1["next_cursor"] is not None

    resp2 = client.get(
        "/users/me/connections",
        params={"limit": 3, "cursor": data1["next_cursor"]},
        headers=headers,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["items"]) == 2
    assert data2["next_cursor"] is None

    all_ids = {i["user_id"] for i in data1["items"] + data2["items"]}
    assert len(all_ids) == 5


@pytest.mark.parametrize("limit", ["0", "-1", "101", "abc", "1.5", ""])
def test_invalid_limit_returns_400(
    conn_client: tuple[TestClient, sessionmaker[Session]],
    limit: str,
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user = create_user(db)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/users/me/connections", params={"limit": limit}, headers=headers)
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid pagination parameters"}


@pytest.mark.parametrize("limit", [1, 100])
def test_valid_limit_boundaries(
    conn_client: tuple[TestClient, sessionmaker[Session]],
    limit: int,
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user = create_user(db)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get("/users/me/connections", params={"limit": limit}, headers=headers)
    assert resp.status_code == 200


def test_malformed_cursor_returns_400(
    conn_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = conn_client
    with session_factory() as db:
        user = create_user(db)
        db.commit()
        headers = make_token(user.user_id)

    resp = client.get(
        "/users/me/connections",
        params={"cursor": "not-a-valid-cursor"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid pagination parameters"}
