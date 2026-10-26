"""Tests for GET /businesses/me.

Follows the pattern from tests/test_follow_business.py:
- SQLite in-memory with StaticPool
- Manually minted JWTs to avoid round-tripping /register
"""

from collections.abc import Iterator
from dataclasses import replace
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
    app.state.testing_session = testing_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def load_user_and_profile(user_id: UUID) -> tuple[UserModel, BusinessProfileModel]:
    with app.state.testing_session() as db:
        user = db.get(UserModel, user_id)
        profile = db.get(BusinessProfileModel, user_id)
        assert user is not None
        assert profile is not None
        return user, profile


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
        "photo_url": None,
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


def test_business_updates_name_description_and_address(client: TestClient) -> None:
    payload = {
        "business_name": "Bar do Zé Atualizado",
        "description": "Bar, petiscaria e música ao vivo",
        "address": "Av. Independência, 200",
        "location": {"latitude": -30.0350, "longitude": -51.2350},
    }
    response = client.patch(URL, headers=_auth(BAR_ID), json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == str(BAR_ID)
    assert data["business_name"] == "Bar do Zé Atualizado"
    assert data["description"] == "Bar, petiscaria e música ao vivo"
    assert data["address"] == "Av. Independência, 200"
    assert data["location"] == {"latitude": -30.0350, "longitude": -51.2350}
    assert "updated_at" in data

    # Verify reflecting in own/public profile (GET /businesses/me)
    get_res = client.get(URL, headers=_auth(BAR_ID))
    assert get_res.status_code == 200
    profile = get_res.json()
    assert profile["business_name"] == "Bar do Zé Atualizado"
    assert profile["description"] == "Bar, petiscaria e música ao vivo"
    assert profile["address"] == "Av. Independência, 200"
    assert profile["location"] == {"latitude": -30.0350, "longitude": -51.2350}
    assert profile["cnpj"] == "12345678000199"

    # Verify persistence in database
    user, profile_model = load_user_and_profile(BAR_ID)
    assert user.name == "Bar do Zé Atualizado"
    assert user.description == "Bar, petiscaria e música ao vivo"
    assert profile_model.address == "Av. Independência, 200"
    assert profile_model.business_latitude == -30.0350
    assert profile_model.business_longitude == -51.2350


def test_personal_user_cannot_patch_business_profile_gets_403(
    client: TestClient,
) -> None:
    response = client.patch(
        URL,
        headers=_auth(PERSON_ID),
        json={"business_name": "Tentativa"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Not a business profile"}


def test_business_user_without_profile_row_gets_403_on_patch(
    client: TestClient,
) -> None:
    response = client.patch(
        URL,
        headers=_auth(ORPHAN_BUSINESS_ID),
        json={"business_name": "Tentativa"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Not a business profile"}


def test_cnpj_sent_in_payload_is_ignored(client: TestClient) -> None:
    response = client.patch(
        URL,
        headers=_auth(BAR_ID),
        json={"cnpj": "99999999000199", "business_name": "Nome Novo"},
    )
    assert response.status_code == 200
    assert response.json()["business_name"] == "Nome Novo"

    user, profile_model = load_user_and_profile(BAR_ID)
    assert profile_model.cnpj == "12345678000199"
    assert user.name == "Nome Novo"


@pytest.mark.parametrize(
    "location",
    [
        {"latitude": 90.1, "longitude": -51.23},
        {"latitude": -90.1, "longitude": -51.23},
        {"latitude": -30.0, "longitude": 180.1},
        {"latitude": -30.0, "longitude": -180.1},
    ],
)
def test_invalid_coordinates_return_400(
    client: TestClient, location: dict[str, float]
) -> None:
    response = client.patch(
        URL,
        headers=_auth(BAR_ID),
        json={"location": location},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid coordinates"}


def test_updated_at_changes_on_every_edit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.services import business_profile as bp_service

    times = [
        datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 23, 12, 5, 0, tzinfo=UTC),
    ]
    time_iter = iter(times)
    monkeypatch.setattr(bp_service, "_now_utc", lambda: next(time_iter))

    first = client.patch(URL, headers=_auth(BAR_ID), json={"business_name": "Nome 1"})
    assert first.status_code == 200
    assert first.json()["updated_at"] == "2026-08-23T12:00:00Z"

    second = client.patch(URL, headers=_auth(BAR_ID), json={"address": "Rua 2"})
    assert second.status_code == 200
    assert second.json()["updated_at"] == "2026-08-23T12:05:00Z"

    # Resending the same values keeps updated_at unchanged
    third = client.patch(
        URL,
        headers=_auth(BAR_ID),
        json={"business_name": "Nome 1", "address": "Rua 2"},
    )
    assert third.status_code == 200
    assert third.json()["updated_at"] == "2026-08-23T12:05:00Z"

    user, profile_model = load_user_and_profile(BAR_ID)
    expected = datetime(2026, 8, 23, 12, 5, 0)
    assert user.updated_at.replace(tzinfo=None) == expected
    assert profile_model.updated_at.replace(tzinfo=None) == expected


def test_business_updates_name_description_and_address_without_location(
    client: TestClient,
) -> None:
    payload = {
        "business_name": "Bar do Zé Novo Nome",
        "description": "Nova descrição sem mexer no mapa",
        "address": "Av. Independência, 300",
    }
    response = client.patch(URL, headers=_auth(BAR_ID), json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["business_name"] == "Bar do Zé Novo Nome"
    assert data["description"] == "Nova descrição sem mexer no mapa"
    assert data["address"] == "Av. Independência, 300"
    assert data["location"] == {"latitude": -30.0331, "longitude": -51.23}


def test_business_updates_only_location(client: TestClient) -> None:
    payload = {
        "location": {"latitude": -30.0400, "longitude": -51.2400},
    }
    response = client.patch(URL, headers=_auth(BAR_ID), json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["location"] == {"latitude": -30.0400, "longitude": -51.2400}
    assert data["business_name"] == "Bar do Zé"
    assert data["address"] == "Av. Independência, 100"


def test_extra_fields_in_payload_are_ignored(client: TestClient) -> None:
    response = client.patch(
        URL,
        headers=_auth(BAR_ID),
        json={
            "business_name": "Bar Seguro",
            "email": "hacked@hangy.test",
            "role": "ADMIN",
            "user_type": "PERSONAL",
        },
    )
    assert response.status_code == 200
    assert response.json()["business_name"] == "Bar Seguro"

    user, _ = load_user_and_profile(BAR_ID)
    assert user.name == "Bar Seguro"
    assert user.email == "bar@hangy.test"
    assert user.role == UserRoleEnum.USER
    assert user.user_type == UserTypeEnum.BUSINESS


def test_description_can_be_cleared_with_null(client: TestClient) -> None:
    response = client.patch(URL, headers=_auth(BAR_ID), json={"description": None})
    assert response.status_code == 200
    assert response.json()["description"] is None

    user, _ = load_user_and_profile(BAR_ID)
    assert user.description is None


def test_empty_payload_changes_nothing(client: TestClient) -> None:
    get_before = client.get(URL, headers=_auth(BAR_ID)).json()
    response = client.patch(URL, headers=_auth(BAR_ID), json={})
    assert response.status_code == 200
    data = response.json()
    assert data["business_name"] == get_before["business_name"]
    assert data["description"] == get_before["description"]
    assert data["address"] == get_before["address"]
    assert data["location"] == get_before["location"]


@pytest.mark.parametrize(
    "payload",
    [
        {"business_name": None},
        {"business_name": ""},
        {"business_name": "   "},
        {"business_name": "a" * 121},
        {"address": None},
        {"address": ""},
        {"address": "   "},
        {"address": "a" * 256},
        {"location": {"latitude": "invalid", "longitude": 0}},
    ],
)
def test_invalid_fields_return_422(client: TestClient, payload: dict) -> None:
    response = client.patch(URL, headers=_auth(BAR_ID), json=payload)
    assert response.status_code == 422


def test_description_exceeds_max_length_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.presentation.routes import businesses as businesses_routes

    monkeypatch.setattr(
        businesses_routes,
        "settings",
        replace(
            businesses_routes.settings,
            profile_description_max_length=20,
        ),
    )
    response = client.patch(
        URL,
        headers=_auth(BAR_ID),
        json={"description": "a" * 21},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Description exceeds maximum length"}


def test_patch_missing_token_returns_401(client: TestClient) -> None:
    response = client.patch(URL, json={"business_name": "Novo"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_patch_invalid_token_returns_401(client: TestClient) -> None:
    response = client.patch(
        URL,
        headers={"Authorization": "Bearer not-valid"},
        json={"business_name": "Novo"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_patch_deleted_business_is_rejected(client: TestClient) -> None:
    response = client.patch(
        URL, headers=_auth(DELETED_BAR_ID), json={"business_name": "Novo"}
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Account has been deleted"}


def test_openapi_documents_patch_businesses_me(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/businesses/me"]["patch"]
    assert set(operation["responses"]) >= {"200", "400", "401", "403", "422"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BusinessProfileUpdateOutput"
    }
