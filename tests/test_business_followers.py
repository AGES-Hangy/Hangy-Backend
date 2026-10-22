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
from app.domain.enums import UserRoleEnum, UserTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    TagModel,
    UserBlockModel,
    UserFollowModel,
    UserModel,
    user_tag,
)
from app.main import app

BUSINESS_ID = UUID("0f200001-0000-4000-8000-000000000001")
OTHER_BUSINESS_ID = UUID("0f200001-0000-4000-8000-000000000002")
PERSONAL_USER_ID = UUID("0f200001-0000-4000-8000-000000000003")

FOLLOWER_1_ID = UUID("0f200001-0000-4000-8000-000000000011")
FOLLOWER_2_ID = UUID("0f200001-0000-4000-8000-000000000012")
FOLLOWER_3_ID = UUID("0f200001-0000-4000-8000-000000000013")
DELETED_FOLLOWER_ID = UUID("0f200001-0000-4000-8000-000000000014")
BLOCKED_BY_BUSINESS_ID = UUID("0f200001-0000-4000-8000-000000000015")
BLOCKER_OF_BUSINESS_ID = UUID("0f200001-0000-4000-8000-000000000016")

BASE_TIME = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


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
    return BusinessProfileModel(user_id=user_id, cnpj=cnpj, address="Av. Central, 100")


def _auth(user_id: UUID = BUSINESS_ID) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=15)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


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
                _user(BUSINESS_ID, UserTypeEnum.BUSINESS, "Café Hangy"),
                _user(OTHER_BUSINESS_ID, UserTypeEnum.BUSINESS, "Outro Bar"),
                _user(PERSONAL_USER_ID, UserTypeEnum.PERSONAL, "Usuário Pessoal"),
                _user(
                    FOLLOWER_1_ID,
                    UserTypeEnum.PERSONAL,
                    "Ana Cláudia",
                    "https://photo1",
                ),
                _user(
                    FOLLOWER_2_ID, UserTypeEnum.PERSONAL, "João Silva", "https://photo2"
                ),
                _user(FOLLOWER_3_ID, UserTypeEnum.PERSONAL, "Lucas Pereira"),
                _user(
                    DELETED_FOLLOWER_ID,
                    UserTypeEnum.PERSONAL,
                    "Usuário Excluído",
                    deleted_at=BASE_TIME,
                ),
                _user(
                    BLOCKED_BY_BUSINESS_ID,
                    UserTypeEnum.PERSONAL,
                    "Bloqueado Pelo Café",
                ),
                _user(
                    BLOCKER_OF_BUSINESS_ID,
                    UserTypeEnum.PERSONAL,
                    "Bloqueou O Café",
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                _business(BUSINESS_ID, "12345678000199"),
                _business(OTHER_BUSINESS_ID, "98765432000188"),
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


def _seed_tags(client: TestClient, user_id: UUID, tag_names: list[str]) -> None:
    with client.testing_session() as db:  # type: ignore[attr-defined]
        tags = [TagModel(tag_id=uuid4(), tag_name=name) for name in tag_names]
        db.add_all(tags)
        db.flush()
        for tag in tags:
            db.execute(user_tag.insert().values(user_id=user_id, tag_id=tag.tag_id))
        db.commit()


def _seed_block(client: TestClient, blocker_id: UUID, blocked_id: UUID) -> None:
    with client.testing_session() as db:  # type: ignore[attr-defined]
        db.add(UserBlockModel(blocker_id=blocker_id, blocked_id=blocked_id))
        db.commit()


# ---------------------------------------------------------------------------
# Acceptance criteria tests
# ---------------------------------------------------------------------------


def test_empty_followers_returns_empty_items_and_zero_total(client: TestClient) -> None:
    response = client.get("/businesses/me/followers", headers=_auth(BUSINESS_ID))

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "next_cursor": None,
    }


def test_followers_success_contract_and_at_most_three_tags(client: TestClient) -> None:
    _seed_follows(
        client,
        [(FOLLOWER_1_ID, BUSINESS_ID, BASE_TIME)],
    )
    # Seed 4 tags for follower 1, ensuring only at most 3 are returned
    _seed_tags(client, FOLLOWER_1_ID, ["Trilha", "Brunch", "Café", "Música"])

    response = client.get("/businesses/me/followers", headers=_auth(BUSINESS_ID))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["next_cursor"] is None
    assert len(body["items"]) == 1

    item = body["items"][0]
    assert item["user_id"] == str(FOLLOWER_1_ID)
    assert item["name"] == "Ana Cláudia"
    assert item["photo_url"] == "https://photo1"
    # Never return sensitive personal data
    assert "email" not in item
    assert "cpf" not in item
    assert "date_of_birth" not in item
    # Maximum 3 tags
    assert len(item["tags"]) == 3
    tag_names = [t["name"] for t in item["tags"]]
    for tag in item["tags"]:
        assert "id" in tag
        assert "name" in tag
    # Sorted tags (Brunch, Café, Música)
    assert tag_names == ["Brunch", "Café", "Música"]


def test_followers_paginates_until_next_cursor_is_null(client: TestClient) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_1_ID, BUSINESS_ID, BASE_TIME),
            (FOLLOWER_2_ID, BUSINESS_ID, BASE_TIME + timedelta(hours=1)),
            (FOLLOWER_3_ID, BUSINESS_ID, BASE_TIME + timedelta(hours=2)),
        ],
    )

    page1 = client.get(
        "/businesses/me/followers?limit=2", headers=_auth(BUSINESS_ID)
    ).json()

    assert len(page1["items"]) == 2
    assert page1["total"] == 3
    assert page1["next_cursor"] is not None
    # Ordered newest follow first
    assert [i["user_id"] for i in page1["items"]] == [
        str(FOLLOWER_3_ID),
        str(FOLLOWER_2_ID),
    ]

    page2 = client.get(
        f"/businesses/me/followers?limit=2&cursor={page1['next_cursor']}",
        headers=_auth(BUSINESS_ID),
    ).json()

    assert len(page2["items"]) == 1
    assert page2["total"] == 3
    assert page2["next_cursor"] is None
    assert [i["user_id"] for i in page2["items"]] == [str(FOLLOWER_1_ID)]


def test_followers_pagination_tie_break_on_identical_created_at(
    client: TestClient,
) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_1_ID, BUSINESS_ID, BASE_TIME),
            (FOLLOWER_2_ID, BUSINESS_ID, BASE_TIME),
            (FOLLOWER_3_ID, BUSINESS_ID, BASE_TIME),
        ],
    )

    page1 = client.get(
        "/businesses/me/followers?limit=2", headers=_auth(BUSINESS_ID)
    ).json()
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = client.get(
        f"/businesses/me/followers?limit=2&cursor={page1['next_cursor']}",
        headers=_auth(BUSINESS_ID),
    ).json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None

    all_ids = [i["user_id"] for i in page1["items"]] + [
        i["user_id"] for i in page2["items"]
    ]
    # Follower IDs are sorted desc: FOLLOWER_3_ID > FOLLOWER_2_ID > FOLLOWER_1_ID
    assert all_ids == [str(FOLLOWER_3_ID), str(FOLLOWER_2_ID), str(FOLLOWER_1_ID)]


def test_followers_search_by_part_of_name_with_and_without_accent(
    client: TestClient,
) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_1_ID, BUSINESS_ID, BASE_TIME),
            (FOLLOWER_2_ID, BUSINESS_ID, BASE_TIME + timedelta(hours=1)),
            (FOLLOWER_3_ID, BUSINESS_ID, BASE_TIME + timedelta(hours=2)),
        ],
    )

    # 1. Search without accent matching without accent
    resp_ana = client.get("/businesses/me/followers?q=ana", headers=_auth(BUSINESS_ID))
    assert resp_ana.status_code == 200
    body_ana = resp_ana.json()
    assert [i["name"] for i in body_ana["items"]] == ["Ana Cláudia"]
    assert body_ana["total"] == 3  # total ignores q

    # 2. Search with accent matching name with accent
    resp_claudia_accent = client.get(
        "/businesses/me/followers?q=cláudia", headers=_auth(BUSINESS_ID)
    )
    assert resp_claudia_accent.status_code == 200
    assert [i["name"] for i in resp_claudia_accent.json()["items"]] == ["Ana Cláudia"]
    assert resp_claudia_accent.json()["total"] == 3

    # 3. Search without accent matching name with accent
    resp_claudia_no_accent = client.get(
        "/businesses/me/followers?q=claudia", headers=_auth(BUSINESS_ID)
    )
    assert resp_claudia_no_accent.status_code == 200
    assert [i["name"] for i in resp_claudia_no_accent.json()["items"]] == [
        "Ana Cláudia"
    ]
    assert resp_claudia_no_accent.json()["total"] == 3

    # 4. Search João with and without accent
    resp_joao_accent = client.get(
        "/businesses/me/followers?q=joão", headers=_auth(BUSINESS_ID)
    )
    assert resp_joao_accent.status_code == 200
    assert [i["name"] for i in resp_joao_accent.json()["items"]] == ["João Silva"]

    resp_joao_no_accent = client.get(
        "/businesses/me/followers?q=joao", headers=_auth(BUSINESS_ID)
    )
    assert resp_joao_no_accent.status_code == 200
    assert [i["name"] for i in resp_joao_no_accent.json()["items"]] == ["João Silva"]


def test_followers_q_with_one_character_returns_422(client: TestClient) -> None:
    response = client.get("/businesses/me/followers?q=a", headers=_auth(BUSINESS_ID))

    assert response.status_code == 422


def test_followers_personal_user_returns_403(client: TestClient) -> None:
    response = client.get("/businesses/me/followers", headers=_auth(PERSONAL_USER_ID))

    assert response.status_code == 403
    assert response.json() == {"detail": "Not a business profile"}


def test_followers_unauthenticated_returns_401(client: TestClient) -> None:
    response = client.get("/businesses/me/followers")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_followers_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get(
        "/businesses/me/followers", headers={"Authorization": "Bearer invalid"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_followers_excludes_blocked_users_in_both_directions(
    client: TestClient,
) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_1_ID, BUSINESS_ID, BASE_TIME),
            (BLOCKED_BY_BUSINESS_ID, BUSINESS_ID, BASE_TIME + timedelta(hours=1)),
            (BLOCKER_OF_BUSINESS_ID, BUSINESS_ID, BASE_TIME + timedelta(hours=2)),
        ],
    )
    # Business blocks BLOCKED_BY_BUSINESS_ID
    _seed_block(client, BUSINESS_ID, BLOCKED_BY_BUSINESS_ID)
    # BLOCKER_OF_BUSINESS_ID blocks Business
    _seed_block(client, BLOCKER_OF_BUSINESS_ID, BUSINESS_ID)

    response = client.get("/businesses/me/followers", headers=_auth(BUSINESS_ID))

    assert response.status_code == 200
    body = response.json()
    assert [i["user_id"] for i in body["items"]] == [str(FOLLOWER_1_ID)]
    assert body["total"] == 1


def test_followers_excludes_soft_deleted_accounts(client: TestClient) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_1_ID, BUSINESS_ID, BASE_TIME),
            (DELETED_FOLLOWER_ID, BUSINESS_ID, BASE_TIME + timedelta(hours=1)),
        ],
    )

    response = client.get("/businesses/me/followers", headers=_auth(BUSINESS_ID))

    assert response.status_code == 200
    body = response.json()
    assert [i["user_id"] for i in body["items"]] == [str(FOLLOWER_1_ID)]
    assert body["total"] == 1


def test_followers_isolates_by_business(client: TestClient) -> None:
    _seed_follows(
        client,
        [
            (FOLLOWER_1_ID, BUSINESS_ID, BASE_TIME),
            (FOLLOWER_2_ID, OTHER_BUSINESS_ID, BASE_TIME),
        ],
    )

    response = client.get("/businesses/me/followers", headers=_auth(BUSINESS_ID))

    assert response.status_code == 200
    body = response.json()
    assert [i["user_id"] for i in body["items"]] == [str(FOLLOWER_1_ID)]
    assert body["total"] == 1


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "cursor=not-a-cursor"],
)
def test_followers_invalid_pagination_returns_400(
    client: TestClient, query: str
) -> None:
    response = client.get(
        f"/businesses/me/followers?{query}", headers=_auth(BUSINESS_ID)
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_followers_non_integer_limit_returns_422(client: TestClient) -> None:
    response = client.get(
        "/businesses/me/followers?limit=abc", headers=_auth(BUSINESS_ID)
    )

    assert response.status_code == 422
