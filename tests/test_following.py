from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    UserFollowModel,
    UserModel,
)
from app.main import app

FOLLOWER_ID = UUID("0f100001-0000-4000-8000-000000000001")
OTHER_PERSON_ID = UUID("0f100001-0000-4000-8000-000000000002")
# UUID order (A < B < C) is the opposite of the follow order below and
# different from the name order, so a wrong ORDER BY cannot pass by luck.
BUSINESS_A_ID = UUID("0f100001-0000-4000-8000-0000000000a1")
BUSINESS_B_ID = UUID("0f100001-0000-4000-8000-0000000000b2")
BUSINESS_C_ID = UUID("0f100001-0000-4000-8000-0000000000c3")
DELETED_BUSINESS_ID = UUID("0f100001-0000-4000-8000-0000000000d4")

BASE_TIME = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


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

    with testing_session() as db:
        db.add_all(
            [
                _user(FOLLOWER_ID, UserTypeEnum.PERSONAL, "Follower"),
                _user(OTHER_PERSON_ID, UserTypeEnum.PERSONAL, "Other"),
                _user(BUSINESS_A_ID, UserTypeEnum.BUSINESS, "Zeta Bar", "https://a"),
                _user(BUSINESS_B_ID, UserTypeEnum.BUSINESS, "Alfa Bar"),
                _user(BUSINESS_C_ID, UserTypeEnum.BUSINESS, "Mid Bar"),
                _user(
                    DELETED_BUSINESS_ID,
                    UserTypeEnum.BUSINESS,
                    "Gone Bar",
                    deleted_at=BASE_TIME,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                _business(BUSINESS_A_ID, "11222333000181"),
                _business(BUSINESS_B_ID, "11222333000262"),
                _business(BUSINESS_C_ID, "11222333000343"),
                _business(DELETED_BUSINESS_ID, "11222333000424"),
            ]
        )
        db.commit()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        test_client.testing_session = testing_session  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _user(
    user_id: UUID,
    user_type: UserTypeEnum,
    name: str,
    photo_url: str | None = None,
    deleted_at: datetime | None = None,
) -> UserModel:
    return UserModel(
        user_id=user_id,
        user_type=user_type,
        role=UserRoleEnum.USER,
        email=f"{user_id}@hangy.test",
        password_hash="hash",
        name=name,
        profile_photo_url=photo_url,
        deleted_at=deleted_at,
    )


def _business(user_id: UUID, cnpj: str) -> BusinessProfileModel:
    return BusinessProfileModel(user_id=user_id, cnpj=cnpj, address="Rua X, 1")


def _auth(user_id: UUID = FOLLOWER_ID) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_follows(
    client: TestClient, follows: list[tuple[UUID, UUID, datetime]]
) -> None:
    with client.testing_session() as db:  # type: ignore[attr-defined]
        db.add_all(
            [
                UserFollowModel(
                    follower_id=follower, followed_business_id=business, created_at=at
                )
                for follower, business, at in follows
            ]
        )
        db.commit()


def _ids(response_json: dict) -> list[str]:
    return [item["user_id"] for item in response_json["items"]]


def test_follow_then_appears_in_following(client: TestClient) -> None:
    follow = client.post(f"/businesses/{BUSINESS_A_ID}/follow", headers=_auth())
    response = client.get("/users/me/following", headers=_auth())

    assert follow.status_code == 204
    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["user_id"] == str(BUSINESS_A_ID)
    assert item["business_name"] == "Zeta Bar"
    assert item["photo_url"] == "https://a"
    assert item["city"] is None
    assert item["followed_at"]


def test_follow_twice_lists_the_business_once(client: TestClient) -> None:
    client.post(f"/businesses/{BUSINESS_A_ID}/follow", headers=_auth())
    client.post(f"/businesses/{BUSINESS_A_ID}/follow", headers=_auth())

    response = client.get("/users/me/following", headers=_auth())

    assert _ids(response.json()) == [str(BUSINESS_A_ID)]


def test_unfollow_removes_from_following(client: TestClient) -> None:
    client.post(f"/businesses/{BUSINESS_A_ID}/follow", headers=_auth())
    client.post(f"/businesses/{BUSINESS_B_ID}/follow", headers=_auth())

    client.delete(f"/businesses/{BUSINESS_A_ID}/follow", headers=_auth())
    response = client.get("/users/me/following", headers=_auth())

    assert _ids(response.json()) == [str(BUSINESS_B_ID)]


def test_following_is_empty_when_following_nobody(client: TestClient) -> None:
    response = client.get("/users/me/following", headers=_auth())

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_following_orders_newest_follow_first(client: TestClient) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_ID, BUSINESS_B_ID, BASE_TIME),
            (FOLLOWER_ID, BUSINESS_C_ID, BASE_TIME + timedelta(hours=2)),
            (FOLLOWER_ID, BUSINESS_A_ID, BASE_TIME + timedelta(hours=1)),
        ],
    )

    response = client.get("/users/me/following", headers=_auth())

    assert _ids(response.json()) == [
        str(BUSINESS_C_ID),
        str(BUSINESS_A_ID),
        str(BUSINESS_B_ID),
    ]


def test_following_excludes_soft_deleted_accounts(client: TestClient) -> None:
    # A stale row can outlive the soft delete; the listing must still hide it.
    _seed_follows(
        client,
        [
            (FOLLOWER_ID, DELETED_BUSINESS_ID, BASE_TIME + timedelta(hours=3)),
            (FOLLOWER_ID, BUSINESS_A_ID, BASE_TIME),
        ],
    )

    response = client.get("/users/me/following", headers=_auth())

    assert _ids(response.json()) == [str(BUSINESS_A_ID)]


def test_following_only_lists_the_callers_follows(client: TestClient) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_ID, BUSINESS_A_ID, BASE_TIME),
            (OTHER_PERSON_ID, BUSINESS_B_ID, BASE_TIME),
        ],
    )

    response = client.get("/users/me/following", headers=_auth())

    assert _ids(response.json()) == [str(BUSINESS_A_ID)]


def test_following_paginates_with_cursor(client: TestClient) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_ID, BUSINESS_A_ID, BASE_TIME),
            (FOLLOWER_ID, BUSINESS_B_ID, BASE_TIME + timedelta(hours=1)),
            (FOLLOWER_ID, BUSINESS_C_ID, BASE_TIME + timedelta(hours=2)),
        ],
    )

    first = client.get("/users/me/following?limit=2", headers=_auth()).json()
    second = client.get(
        f"/users/me/following?limit=2&cursor={first['next_cursor']}",
        headers=_auth(),
    ).json()

    assert _ids(first) == [str(BUSINESS_C_ID), str(BUSINESS_B_ID)]
    assert first["next_cursor"] is not None
    assert _ids(second) == [str(BUSINESS_A_ID)]
    assert second["next_cursor"] is None


def test_following_cursor_breaks_ties_on_equal_timestamps(
    client: TestClient,
) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_ID, BUSINESS_A_ID, BASE_TIME),
            (FOLLOWER_ID, BUSINESS_B_ID, BASE_TIME),
            (FOLLOWER_ID, BUSINESS_C_ID, BASE_TIME),
        ],
    )

    first = client.get("/users/me/following?limit=2", headers=_auth()).json()
    second = client.get(
        f"/users/me/following?limit=2&cursor={first['next_cursor']}",
        headers=_auth(),
    ).json()

    assert _ids(first) + _ids(second) == [
        str(BUSINESS_C_ID),
        str(BUSINESS_B_ID),
        str(BUSINESS_A_ID),
    ]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "cursor=not-a-cursor"])
def test_following_invalid_pagination_returns_400(
    client: TestClient, query: str
) -> None:
    response = client.get(f"/users/me/following?{query}", headers=_auth())

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_following_without_token_returns_401(client: TestClient) -> None:
    response = client.get("/users/me/following")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_following_with_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get(
        "/users/me/following", headers={"Authorization": "Bearer invalid"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
