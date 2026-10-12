from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from itertools import count
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.services import user_profile as user_profile_service
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import PersonProfileModel, UserModel
from app.main import app
from app.presentation.routes import auth as auth_routes

DESCRIPTION_MAX_LENGTH = 20
FIRST_EDIT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

PERSONAL_PAYLOAD = {
    "user_type": "PERSONAL",
    "email": "ana@hangy.com",
    "password": "strong-password",
    "name": "Ana Souza",
    "cpf": "52998224725",
    "phone": "51999990000",
    "date_of_birth": "2000-04-12",
    "state": "RS",
    "city": "Porto Alegre",
    "accepted_terms_version": "2026-08-01",
}

BUSINESS_PAYLOAD = {
    "user_type": "BUSINESS",
    "email": "contato@bar.com",
    "password": "senha-forte-123",
    "business_name": "Bar do Zé",
    "cnpj": "11222333000181",
    "description": "Bar e petiscaria",
    "location": {"latitude": -30.0331, "longitude": -51.23},
    "address": "Av. Independência, 100 — Porto Alegre",
    "accepted_terms_version": "2026-08-01",
}


@dataclass
class Context:
    client: TestClient
    db: Session


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Context]:
    # A small limit, independent of the environment, so the boundary is exact.
    monkeypatch.setattr(
        auth_routes,
        "settings",
        replace(
            auth_routes.settings,
            profile_description_max_length=DESCRIPTION_MAX_LENGTH,
        ),
    )
    # Each edit happens one minute after the previous one.
    minutes = count()
    monkeypatch.setattr(
        user_profile_service,
        "_now_utc",
        lambda: FIRST_EDIT.replace(minute=next(minutes)),
    )
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
    with testing_session() as db, TestClient(app) as test_client:
        yield Context(client=test_client, db=db)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def register(client: TestClient, payload: dict) -> tuple[UUID, dict[str, str]]:
    """Register a user and return (user_id, auth headers)."""
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    body = response.json()
    return UUID(body["user"]["id"]), {"Authorization": f"Bearer {body['access_token']}"}


def load(db: Session, user_id: UUID) -> tuple[UserModel, PersonProfileModel]:
    db.expire_all()
    return db.get(UserModel, user_id), db.get(PersonProfileModel, user_id)


def patch_profile(client: TestClient, headers: dict[str, str], payload: dict):
    return client.patch("/users/me/profile", headers=headers, json=payload)


def test_full_update_returns_the_edited_profile(ctx: Context) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)

    response = patch_profile(
        ctx.client,
        headers,
        {
            "name": "Ana Lima",
            "description": "Curto futebol",
            "country": "BR",
            "state": "SC",
            "city": "Florianópolis",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "name": "Ana Lima",
        "description": "Curto futebol",
        "city": "Florianópolis",
        "updated_at": "2026-10-05T12:00:00Z",
    }
    user, profile = load(ctx.db, user_id)
    assert (user.name, user.description) == ("Ana Lima", "Curto futebol")
    assert (profile.state, profile.city) == ("SC", "Florianópolis")
    # The profile screen reads the same columns.
    profile_screen = ctx.client.get("/users/me/profile", headers=headers).json()
    assert profile_screen["profile"]["name"] == "Ana Lima"
    assert profile_screen["profile"]["description"] == "Curto futebol"


def test_updating_only_the_bio_keeps_name_and_location(ctx: Context) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)

    response = patch_profile(ctx.client, headers, {"description": "Curto pagode"})

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ana Souza"
    assert body["description"] == "Curto pagode"
    assert body["city"] == "Porto Alegre"
    user, profile = load(ctx.db, user_id)
    assert user.name == "Ana Souza"
    assert (profile.state, profile.city) == ("RS", "Porto Alegre")


def test_bio_above_the_limit_returns_400(ctx: Context) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)

    response = patch_profile(
        ctx.client, headers, {"description": "x" * (DESCRIPTION_MAX_LENGTH + 1)}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Description exceeds maximum length"}
    user, _ = load(ctx.db, user_id)
    assert user.description is None


def test_bio_at_the_limit_is_accepted(ctx: Context) -> None:
    _, headers = register(ctx.client, PERSONAL_PAYLOAD)
    description = "x" * DESCRIPTION_MAX_LENGTH

    response = patch_profile(ctx.client, headers, {"description": description})

    assert response.status_code == 200
    assert response.json()["description"] == description


def test_bio_can_be_cleared_with_null(ctx: Context) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)
    patch_profile(ctx.client, headers, {"description": "Curto pagode"})

    response = patch_profile(ctx.client, headers, {"description": None})

    assert response.status_code == 200
    assert response.json()["description"] is None
    user, _ = load(ctx.db, user_id)
    assert user.description is None


def test_cpf_email_and_date_of_birth_are_ignored(ctx: Context) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)

    response = patch_profile(
        ctx.client,
        headers,
        {
            "cpf": "11144477735",
            "email": "outra@hangy.com",
            "date_of_birth": "1990-01-01",
            "city": "Canoas",
        },
    )

    assert response.status_code == 200
    assert response.json()["city"] == "Canoas"
    user, profile = load(ctx.db, user_id)
    assert user.email == PERSONAL_PAYLOAD["email"]
    assert profile.cpf == PERSONAL_PAYLOAD["cpf"]
    assert profile.date_of_birth == date(2000, 4, 12)
    assert profile.city == "Canoas"


def test_business_account_returns_403(ctx: Context) -> None:
    user_id, headers = register(ctx.client, BUSINESS_PAYLOAD)

    response = patch_profile(ctx.client, headers, {"description": "Outra bio"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Not a personal profile"}
    user, _ = load(ctx.db, user_id)
    assert user.description == "Bar e petiscaria"


def test_business_account_gets_403_even_with_a_bio_too_long(ctx: Context) -> None:
    _, headers = register(ctx.client, BUSINESS_PAYLOAD)

    response = patch_profile(
        ctx.client, headers, {"description": "x" * (DESCRIPTION_MAX_LENGTH + 1)}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Not a personal profile"}


def test_personal_account_without_profile_row_returns_403(ctx: Context) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)
    ctx.db.execute(
        delete(PersonProfileModel).where(PersonProfileModel.user_id == user_id)
    )
    ctx.db.commit()

    response = patch_profile(ctx.client, headers, {"description": "Oi"})

    assert response.status_code == 403
    assert response.json() == {"detail": "Not a personal profile"}


def test_updated_at_changes_on_every_edit(ctx: Context) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)

    first = patch_profile(ctx.client, headers, {"description": "Primeira"})
    second = patch_profile(ctx.client, headers, {"city": "Canoas"})

    assert first.json()["updated_at"] == "2026-10-05T12:00:00Z"
    assert second.json()["updated_at"] == "2026-10-05T12:01:00Z"
    user, profile = load(ctx.db, user_id)
    expected = datetime(2026, 10, 5, 12, 1)
    # SQLite drops tzinfo on read.
    assert profile.updated_at.replace(tzinfo=None) == expected
    assert user.updated_at.replace(tzinfo=None) == expected


def test_resending_the_current_values_keeps_updated_at(ctx: Context) -> None:
    _, headers = register(ctx.client, PERSONAL_PAYLOAD)
    first = patch_profile(ctx.client, headers, {"description": "Primeira"})

    response = patch_profile(
        ctx.client, headers, {"description": "Primeira", "city": "Porto Alegre"}
    )

    assert response.status_code == 200
    assert response.json() == first.json()


def test_empty_payload_changes_nothing(ctx: Context) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)
    registered_at = datetime(2026, 1, 1, 9, 30)
    ctx.db.execute(
        update(PersonProfileModel)
        .where(PersonProfileModel.user_id == user_id)
        .values(updated_at=registered_at)
    )
    ctx.db.commit()

    response = patch_profile(ctx.client, headers, {})

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "name": "Ana Souza",
        "description": None,
        "city": "Porto Alegre",
        "updated_at": "2026-01-01T09:30:00Z",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"city": None},
        {"state": ""},
        {"name": "   "},
        {"name": "x" * 121},
        {"city": "x" * 101},
        {"description": 123},
    ],
)
def test_invalid_fields_return_422(ctx: Context, payload: dict) -> None:
    user_id, headers = register(ctx.client, PERSONAL_PAYLOAD)

    response = patch_profile(ctx.client, headers, payload)

    assert response.status_code == 422
    user, profile = load(ctx.db, user_id)
    assert user.name == "Ana Souza"
    assert (profile.state, profile.city) == ("RS", "Porto Alegre")


def test_missing_token_returns_401(ctx: Context) -> None:
    response = ctx.client.patch("/users/me/profile", json={"description": "Oi"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_invalid_token_returns_401(ctx: Context) -> None:
    response = patch_profile(
        ctx.client, {"Authorization": "Bearer not-a-jwt"}, {"description": "Oi"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_openapi_documents_the_patch_route(ctx: Context) -> None:
    operation = ctx.client.get("/openapi.json").json()["paths"]["/users/me/profile"][
        "patch"
    ]

    assert set(operation["responses"]) >= {"200", "400", "401", "403", "422"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserProfileUpdateOutput"
    }
