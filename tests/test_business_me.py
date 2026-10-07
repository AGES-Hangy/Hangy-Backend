"""Tests for GET /businesses/me.

Follows the pattern from tests/test_follow_business.py:
- SQLite in-memory with StaticPool
- Manually minted JWTs to avoid round-tripping /register
"""

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
from app.infrastructure.repository.models import BusinessProfileModel, UserModel
from app.main import app

URL = "/businesses/me"

BAR_ID = UUID("0f000077-0000-4000-8000-000000000001")
OTHER_BAR_ID = UUID("0f000077-0000-4000-8000-000000000002")
NO_COORDINATES_ID = UUID("0f000077-0000-4000-8000-000000000003")
PERSON_ID = UUID("0f000077-0000-4000-8000-000000000004")
ORPHAN_BUSINESS_ID = UUID("0f000077-0000-4000-8000-000000000005")
DELETED_BAR_ID = UUID("0f000077-0000-4000-8000-000000000006")


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
                _user(
                    BAR_ID,
                    UserTypeEnum.BUSINESS,
                    "bar@hangy.test",
                    name="Bar do Zé",
                    description="Bar e petiscaria",
                    user_phone="5133330000",
                ),
                _user(
                    OTHER_BAR_ID,
                    UserTypeEnum.BUSINESS,
                    "other-bar@hangy.test",
                    name="Outro Bar",
                ),
                _user(
                    NO_COORDINATES_ID,
                    UserTypeEnum.BUSINESS,
                    "no-coordinates@hangy.test",
                    name="Sem Mapa",
                ),
                _user(PERSON_ID, UserTypeEnum.PERSONAL, "person@hangy.test"),
                _user(ORPHAN_BUSINESS_ID, UserTypeEnum.BUSINESS, "orphan@hangy.test"),
                _user(
                    DELETED_BAR_ID,
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
                    user_id=BAR_ID,
                    cnpj="12345678000199",
                    address="Av. Independência, 100",
                    business_latitude=-30.0331,
                    business_longitude=-51.23,
                ),
                BusinessProfileModel(
                    user_id=OTHER_BAR_ID,
                    cnpj="11222333000181",
                    address="Rua Outra, 1",
                    business_latitude=-30.1,
                    business_longitude=-51.1,
                ),
                BusinessProfileModel(
                    user_id=NO_COORDINATES_ID,
                    cnpj="11222333000262",
                    address="Rua Sem Ponto, 2",
                ),
                BusinessProfileModel(
                    user_id=DELETED_BAR_ID,
                    cnpj="11222333000343",
                    address="Rua Fechada, 3",
                ),
            ]
        )
        db.commit()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _user(
    user_id: UUID,
    user_type: UserTypeEnum,
    email: str,
    *,
    name: str | None = None,
    description: str | None = None,
    user_phone: str | None = None,
    deleted_at: datetime | None = None,
) -> UserModel:
    return UserModel(
        user_id=user_id,
        user_type=user_type,
        role=UserRoleEnum.USER,
        email=email,
        password_hash="hash",
        name=name,
        description=description,
        user_phone=user_phone,
        deleted_at=deleted_at,
    )


def _auth(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=30)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def test_business_reads_its_own_profile(client: TestClient) -> None:
    response = client.get(URL, headers=_auth(BAR_ID))

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(BAR_ID),
        "business_name": "Bar do Zé",
        "cnpj": "12345678000199",
        "description": "Bar e petiscaria",
        "address": "Av. Independência, 100",
        "location": {"latitude": -30.0331, "longitude": -51.23},
        "phone": "5133330000",
    }


def test_each_business_only_sees_its_own_profile(client: TestClient) -> None:
    response = client.get(URL, headers=_auth(OTHER_BAR_ID))

    body = response.json()
    assert response.status_code == 200
    assert body["user_id"] == str(OTHER_BAR_ID)
    assert body["cnpj"] == "11222333000181"
    assert body["business_name"] == "Outro Bar"


def test_business_without_coordinates_gets_null_location(client: TestClient) -> None:
    response = client.get(URL, headers=_auth(NO_COORDINATES_ID))

    body = response.json()
    assert response.status_code == 200
    assert body["location"] is None
    assert body["address"] == "Rua Sem Ponto, 2"
    assert body["description"] is None
    assert body["phone"] is None


def test_personal_user_gets_403(client: TestClient) -> None:
    response = client.get(URL, headers=_auth(PERSON_ID))

    assert response.status_code == 403
    assert response.json() == {"detail": "Not a business profile"}


def test_business_user_without_profile_row_gets_403(client: TestClient) -> None:
    response = client.get(URL, headers=_auth(ORPHAN_BUSINESS_ID))

    assert response.status_code == 403
    assert response.json() == {"detail": "Not a business profile"}


def test_missing_token_returns_401(client: TestClient) -> None:
    response = client.get(URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get(URL, headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_deleted_business_account_is_rejected(client: TestClient) -> None:
    response = client.get(URL, headers=_auth(DELETED_BAR_ID))

    assert response.status_code == 403
    assert response.json() == {"detail": "Account has been deleted"}