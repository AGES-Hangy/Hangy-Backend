from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import ReportTypeEnum
from app.infrastructure.repository import Base, get_db
from app.main import app

USER_EMAIL = "ana@hangy.com"
USER_PASSWORD = "strong-password"


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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def auth_headers(client: TestClient) -> dict[str, str]:
    register = client.post(
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": USER_EMAIL,
            "password": USER_PASSWORD,
            "name": "Ana Souza",
            "cpf": "52998224725",
            "phone": "51999990000",
            "date_of_birth": "2000-04-12",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": "2026-08-01",
        },
    )
    assert register.status_code == 201
    login = client.post(
        "/auth/login", json={"email": USER_EMAIL, "password": USER_PASSWORD}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_user_target_returns_the_user_reasons(client: TestClient) -> None:
    response = client.get(
        "/reports/reasons", params={"target": "USER"}, headers=auth_headers(client)
    )

    assert response.status_code == 200
    body = response.json()
    assert body[0] == {"code": "HARASSMENT", "label": "Abuso"}
    assert {reason["code"] for reason in body} <= {t.value for t in ReportTypeEnum}
    assert "FAKE_PROFILE" in {reason["code"] for reason in body}


def test_event_target_returns_a_different_list(client: TestClient) -> None:
    headers = auth_headers(client)

    user_codes = [
        r["code"]
        for r in client.get(
            "/reports/reasons", params={"target": "USER"}, headers=headers
        ).json()
    ]
    response = client.get(
        "/reports/reasons", params={"target": "EVENT"}, headers=headers
    )

    assert response.status_code == 200
    event_codes = [reason["code"] for reason in response.json()]
    assert event_codes != user_codes
    assert "FAKE_PROFILE" not in event_codes
    assert all(set(reason) == {"code", "label"} for reason in response.json())


@pytest.mark.parametrize("params", [{}, {"target": "BUSINESS"}, {"target": "user"}])
def test_missing_or_invalid_target_returns_422(
    client: TestClient, params: dict[str, str]
) -> None:
    response = client.get(
        "/reports/reasons", params=params, headers=auth_headers(client)
    )

    assert response.status_code == 422


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/reports/reasons", params={"target": "USER"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}

    response = client.get(
        "/reports/reasons",
        params={"target": "USER"},
        headers={"Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401
