from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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

FOLLOWER_ID = UUID("0f000001-0000-4000-8000-000000000001")
BUSINESS_ID = UUID("0f000001-0000-4000-8000-000000000002")
OTHER_PERSON_ID = UUID("0f000001-0000-4000-8000-000000000003")
DELETED_BUSINESS_ID = UUID("0f000001-0000-4000-8000-000000000004")
MISSING_ID = UUID("0f000001-0000-4000-8000-0000000000ff")


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
                _user(FOLLOWER_ID, UserTypeEnum.PERSONAL, "follower@hangy.test"),
                _user(BUSINESS_ID, UserTypeEnum.BUSINESS, "bar@hangy.test"),
                _user(OTHER_PERSON_ID, UserTypeEnum.PERSONAL, "other@hangy.test"),
                _user(
                    DELETED_BUSINESS_ID,
                    UserTypeEnum.BUSINESS,
                    "gone@hangy.test",
                    deleted_at=datetime.now(UTC),
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                BusinessProfileModel(
                    user_id=BUSINESS_ID,
                    cnpj="11222333000181",
                    address="Av. Independência, 100",
                ),
                BusinessProfileModel(
                    user_id=DELETED_BUSINESS_ID,
                    cnpj="11222333000262",
                    address="Rua Fechada, 1",
                ),
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
    email: str,
    deleted_at: datetime | None = None,
) -> UserModel:
    return UserModel(
        user_id=user_id,
        user_type=user_type,
        role=UserRoleEnum.USER,
        email=email,
        password_hash="hash",
        name=email,
        deleted_at=deleted_at,
    )


def _auth(user_id: UUID = FOLLOWER_ID) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _follow_rows(client: TestClient) -> list[tuple[UUID, UUID]]:
    with client.testing_session() as db:  # type: ignore[attr-defined]
        rows = db.execute(
            select(UserFollowModel.follower_id, UserFollowModel.followed_business_id)
        ).all()
    return [(row[0], row[1]) for row in rows]


def test_follow_business_returns_204_and_persists_the_follow(
    client: TestClient,
) -> None:
    response = client.post(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())

    assert response.status_code == 204
    assert response.content == b""
    assert _follow_rows(client) == [(FOLLOWER_ID, BUSINESS_ID)]


def test_follow_business_twice_is_idempotent(client: TestClient) -> None:
    first = client.post(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())
    second = client.post(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())

    assert first.status_code == 204
    assert second.status_code == 204
    with client.testing_session() as db:  # type: ignore[attr-defined]
        total = db.scalar(select(func.count()).select_from(UserFollowModel))
    assert total == 1


def test_follow_personal_profile_returns_403(client: TestClient) -> None:
    response = client.post(f"/businesses/{OTHER_PERSON_ID}/follow", headers=_auth())

    assert response.status_code == 403
    assert response.json() == {"detail": "Target is not a business profile"}
    assert _follow_rows(client) == []


def test_follow_missing_business_returns_404(client: TestClient) -> None:
    response = client.post(f"/businesses/{MISSING_ID}/follow", headers=_auth())

    assert response.status_code == 404
    assert response.json() == {"detail": "Business not found"}


def test_follow_deleted_business_returns_404(client: TestClient) -> None:
    response = client.post(f"/businesses/{DELETED_BUSINESS_ID}/follow", headers=_auth())

    assert response.status_code == 404
    assert response.json() == {"detail": "Business not found"}
    assert _follow_rows(client) == []


def test_follow_without_token_returns_401(client: TestClient) -> None:
    response = client.post(f"/businesses/{BUSINESS_ID}/follow")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_follow_with_invalid_token_returns_401(client: TestClient) -> None:
    response = client.post(
        f"/businesses/{BUSINESS_ID}/follow",
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_unfollow_business_returns_204_and_removes_the_follow(
    client: TestClient,
) -> None:
    client.post(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())

    response = client.delete(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())

    assert response.status_code == 204
    assert response.content == b""
    assert _follow_rows(client) == []


def test_unfollow_business_not_followed_is_idempotent(client: TestClient) -> None:
    first = client.delete(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())
    second = client.delete(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())

    assert first.status_code == 204
    assert second.status_code == 204
    assert _follow_rows(client) == []


def test_unfollow_only_removes_the_callers_follow(client: TestClient) -> None:
    client.post(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())
    client.post(f"/businesses/{BUSINESS_ID}/follow", headers=_auth(OTHER_PERSON_ID))

    response = client.delete(f"/businesses/{BUSINESS_ID}/follow", headers=_auth())

    assert response.status_code == 204
    assert _follow_rows(client) == [(OTHER_PERSON_ID, BUSINESS_ID)]


def test_unfollow_missing_business_returns_404(client: TestClient) -> None:
    response = client.delete(f"/businesses/{MISSING_ID}/follow", headers=_auth())

    assert response.status_code == 404
    assert response.json() == {"detail": "Business not found"}


def test_unfollow_deleted_business_returns_404(client: TestClient) -> None:
    response = client.delete(
        f"/businesses/{DELETED_BUSINESS_ID}/follow", headers=_auth()
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Business not found"}


def test_unfollow_personal_profile_returns_404(client: TestClient) -> None:
    response = client.delete(f"/businesses/{OTHER_PERSON_ID}/follow", headers=_auth())

    assert response.status_code == 404
    assert response.json() == {"detail": "Business not found"}


def test_unfollow_without_token_returns_401(client: TestClient) -> None:
    response = client.delete(f"/businesses/{BUSINESS_ID}/follow")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_unfollow_with_invalid_token_returns_401(client: TestClient) -> None:
    response = client.delete(
        f"/businesses/{BUSINESS_ID}/follow",
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
