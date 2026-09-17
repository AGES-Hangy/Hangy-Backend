from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserModel
from app.main import app

TERMS_VERSION = "2026-08-01"

VALID_PERSONAL_PAYLOAD = {
    "user_type": "PERSONAL",
    "email": "ana@exemplo.com",
    "password": "senha-forte-123",
    "name": "Ana Souza",
    "cpf": "52998224725",
    "phone": "51999990000",
    "date_of_birth": "2000-04-12",
    "country": "BR",
    "state": "RS",
    "city": "Porto Alegre",
    "accepted_terms_version": TERMS_VERSION,
}

VALID_BUSINESS_PAYLOAD = {
    "user_type": "BUSINESS",
    "email": "contato@bar.com",
    "password": "senha-forte-123",
    "business_name": "Bar do Zé",
    "cnpj": "11222333000181",
    "phone": "5133330000",
    "description": "Bar e petiscaria",
    "location": {"latitude": -30.0331, "longitude": -51.23},
    "address": "Av. Independência, 100 — Porto Alegre",
    "accepted_terms_version": TERMS_VERSION,
}


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

    app.dependency_overrides[get_db] = override_get_db
    with testing_session() as db, TestClient(app) as test_client:
        test_client.db = db  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_register_personal_returns_201_with_token_and_hashed_password(
    client: TestClient,
) -> None:
    response = client.post("/register", json=VALID_PERSONAL_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["user_type"] == "PERSONAL"
    assert body["user"]["email"] == VALID_PERSONAL_PAYLOAD["email"]
    assert body["user"]["name"] == VALID_PERSONAL_PAYLOAD["name"]

    db: Session = client.db  # type: ignore[attr-defined]
    user = db.scalar(
        select(UserModel).where(UserModel.email == VALID_PERSONAL_PAYLOAD["email"])
    )
    assert user is not None
    assert user.password_hash != VALID_PERSONAL_PAYLOAD["password"]


def test_register_business_returns_201_with_token(client: TestClient) -> None:
    response = client.post("/register", json=VALID_BUSINESS_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["user_type"] == "BUSINESS"
    assert body["user"]["business_name"] == VALID_BUSINESS_PAYLOAD["business_name"]


def test_invalid_cpf_returns_400(client: TestClient) -> None:
    payload = {**VALID_PERSONAL_PAYLOAD, "cpf": "12345678900"}

    response = client.post("/register", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "CPF is invalid"}


def test_invalid_cnpj_returns_400(client: TestClient) -> None:
    payload = {**VALID_BUSINESS_PAYLOAD, "cnpj": "12345678000199"}

    response = client.post("/register", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "CNPJ is invalid"}


@pytest.mark.parametrize(
    "location",
    [
        {"latitude": 91, "longitude": -51.23},
        {"latitude": -30.0331, "longitude": 181},
    ],
)
def test_invalid_coordinates_return_400(
    client: TestClient, location: dict[str, float]
) -> None:
    payload = {**VALID_BUSINESS_PAYLOAD, "location": location}

    response = client.post("/register", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid coordinates"}


def test_underage_personal_registration_returns_403(client: TestClient) -> None:
    fifteen_years_ago = (
        datetime.now(UTC).date().replace(year=datetime.now(UTC).year - 15)
    )
    payload = {
        **VALID_PERSONAL_PAYLOAD,
        "date_of_birth": fifteen_years_ago.isoformat(),
    }

    response = client.post("/register", json=payload)

    assert response.status_code == 403
    assert response.json() == {"detail": "Minimum age is 18 years"}


def test_duplicate_email_returns_409_for_personal_and_business(
    client: TestClient,
) -> None:
    assert client.post("/register", json=VALID_PERSONAL_PAYLOAD).status_code == 201

    duplicate_personal = {
        **VALID_PERSONAL_PAYLOAD,
        "cpf": "11144477735",
    }
    response = client.post("/register", json=duplicate_personal)
    assert response.status_code == 409
    assert response.json() == {"detail": "Email is already registered"}

    duplicate_business = {
        **VALID_BUSINESS_PAYLOAD,
        "email": VALID_PERSONAL_PAYLOAD["email"],
    }
    response = client.post("/register", json=duplicate_business)
    assert response.status_code == 409
    assert response.json() == {"detail": "Email is already registered"}


def test_duplicate_cpf_returns_409(client: TestClient) -> None:
    assert client.post("/register", json=VALID_PERSONAL_PAYLOAD).status_code == 201

    payload = {**VALID_PERSONAL_PAYLOAD, "email": "outra@exemplo.com"}
    response = client.post("/register", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "CPF is already registered"}


def test_duplicate_cnpj_returns_409(client: TestClient) -> None:
    assert client.post("/register", json=VALID_BUSINESS_PAYLOAD).status_code == 201

    payload = {**VALID_BUSINESS_PAYLOAD, "email": "outro@bar.com"}
    response = client.post("/register", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "CNPJ is already registered"}


def test_email_used_by_personal_blocks_business_with_same_email(
    client: TestClient,
) -> None:
    assert client.post("/register", json=VALID_PERSONAL_PAYLOAD).status_code == 201

    payload = {**VALID_BUSINESS_PAYLOAD, "email": VALID_PERSONAL_PAYLOAD["email"]}
    response = client.post("/register", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "Email is already registered"}


def test_email_used_by_business_blocks_personal_with_same_email(
    client: TestClient,
) -> None:
    assert client.post("/register", json=VALID_BUSINESS_PAYLOAD).status_code == 201

    payload = {**VALID_PERSONAL_PAYLOAD, "email": VALID_BUSINESS_PAYLOAD["email"]}
    response = client.post("/register", json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "Email is already registered"}


def test_missing_user_type_returns_422(client: TestClient) -> None:
    payload = {
        key: value
        for key, value in VALID_PERSONAL_PAYLOAD.items()
        if key != "user_type"
    }

    response = client.post("/register", json=payload)

    assert response.status_code == 422


def test_invalid_user_type_returns_422(client: TestClient) -> None:
    payload = {**VALID_PERSONAL_PAYLOAD, "user_type": "ADMIN"}

    response = client.post("/register", json=payload)

    assert response.status_code == 422


def test_personal_payload_with_business_fields_returns_422(client: TestClient) -> None:
    payload = {**VALID_PERSONAL_PAYLOAD, "cnpj": "11222333000181"}

    response = client.post("/register", json=payload)

    assert response.status_code == 422


def test_business_payload_with_personal_fields_returns_422(client: TestClient) -> None:
    payload = {**VALID_BUSINESS_PAYLOAD, "cpf": "52998224725"}

    response = client.post("/register", json=payload)

    assert response.status_code == 422


def test_terms_acceptance_persists_timestamp_and_version(client: TestClient) -> None:
    before = datetime.now(UTC)
    response = client.post("/register", json=VALID_PERSONAL_PAYLOAD)
    assert response.status_code == 201

    db: Session = client.db  # type: ignore[attr-defined]
    user = db.scalar(
        select(UserModel).where(UserModel.email == VALID_PERSONAL_PAYLOAD["email"])
    )
    assert user is not None
    assert user.accepted_terms_version == TERMS_VERSION
    assert user.accepted_terms_at is not None
    assert user.accepted_terms_at.replace(tzinfo=UTC) >= before


def test_email_of_a_deleted_account_can_be_reused(client: TestClient) -> None:
    response = client.post("/register", json=VALID_PERSONAL_PAYLOAD)
    assert response.status_code == 201

    db: Session = client.db  # type: ignore[attr-defined]
    user = db.scalar(
        select(UserModel).where(UserModel.email == VALID_PERSONAL_PAYLOAD["email"])
    )
    assert user is not None
    user.deleted_at = datetime.now(UTC)
    db.commit()

    payload = {**VALID_PERSONAL_PAYLOAD, "cpf": "11144477735"}
    response = client.post("/register", json=payload)

    assert response.status_code == 201


def test_business_location_round_trips_the_same_coordinates(
    client: TestClient,
) -> None:
    response = client.post("/register", json=VALID_BUSINESS_PAYLOAD)
    assert response.status_code == 201

    from app.infrastructure.repository.models import BusinessProfileModel

    db: Session = client.db  # type: ignore[attr-defined]
    profile = db.scalar(
        select(BusinessProfileModel).where(
            BusinessProfileModel.cnpj == VALID_BUSINESS_PAYLOAD["cnpj"]
        )
    )
    assert profile is not None
    assert profile.business_latitude == VALID_BUSINESS_PAYLOAD["location"]["latitude"]
    assert profile.business_longitude == VALID_BUSINESS_PAYLOAD["location"]["longitude"]
