from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserBlockModel
from app.main import app

USER_PASSWORD = "strong-password"
CPFS = {
    "ana@hangy.com": "52998224725",
    "bruno@hangy.com": "11144477735",
    "carla@hangy.com": "39053344705",
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
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_user(client: TestClient, email: str) -> tuple[str, str]:
    response = client.post(
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": email,
            "password": USER_PASSWORD,
            "name": "Usuário de Teste",
            "cpf": CPFS[email],
            "phone": "51999990000",
            "date_of_birth": "2000-04-12",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": "2026-08-01",
        },
    )
    assert response.status_code == 201
    body = response.json()
    return body["user"]["id"], body["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def block(client: TestClient, token: str, user_id: str) -> None:
    response = client.post(f"/users/{user_id}/block", headers=auth(token))
    assert response.status_code == 204


def set_blocked_at(blocker_id: str, blocked_id: str, when: datetime) -> None:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        db.execute(
            update(UserBlockModel)
            .where(
                UserBlockModel.blocker_id == UUID(blocker_id),
                UserBlockModel.blocked_id == UUID(blocked_id),
            )
            .values(created_at=when)
        )
        db.commit()
    finally:
        db_generator.close()


def test_lists_blocked_users_with_their_data(client: TestClient) -> None:
    _, token_a = create_user(client, "ana@hangy.com")
    bruno_id, _ = create_user(client, "bruno@hangy.com")
    block(client, token_a, bruno_id)

    response = client.get("/users/me/blocked", headers=auth(token_a))

    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["user_id"] == bruno_id
    assert item["name"] == "Usuário de Teste"
    assert item["photo_url"] is None
    assert item["blocked_at"]


def test_returns_an_empty_list_when_nobody_is_blocked(client: TestClient) -> None:
    _, token_a = create_user(client, "ana@hangy.com")

    response = client.get("/users/me/blocked", headers=auth(token_a))

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_does_not_list_users_who_blocked_me(client: TestClient) -> None:
    ana_id, token_a = create_user(client, "ana@hangy.com")
    bruno_id, token_b = create_user(client, "bruno@hangy.com")
    block(client, token_b, ana_id)

    ana_list = client.get("/users/me/blocked", headers=auth(token_a)).json()
    bruno_list = client.get("/users/me/blocked", headers=auth(token_b)).json()

    assert ana_list["items"] == []
    assert [item["user_id"] for item in bruno_list["items"]] == [ana_id]
    assert bruno_id not in [item["user_id"] for item in ana_list["items"]]


def test_paginates_with_an_opaque_cursor(client: TestClient) -> None:
    ana_id, token_a = create_user(client, "ana@hangy.com")
    bruno_id, _ = create_user(client, "bruno@hangy.com")
    carla_id, _ = create_user(client, "carla@hangy.com")
    block(client, token_a, bruno_id)
    block(client, token_a, carla_id)
    set_blocked_at(ana_id, bruno_id, datetime(2026, 1, 1, 10, tzinfo=UTC))
    set_blocked_at(ana_id, carla_id, datetime(2026, 1, 2, 10, tzinfo=UTC))

    first = client.get(
        "/users/me/blocked", params={"limit": 1}, headers=auth(token_a)
    ).json()
    assert [item["user_id"] for item in first["items"]] == [carla_id]
    assert first["next_cursor"] is not None

    second = client.get(
        "/users/me/blocked",
        params={"limit": 1, "cursor": first["next_cursor"]},
        headers=auth(token_a),
    ).json()
    assert [item["user_id"] for item in second["items"]] == [bruno_id]
    assert second["next_cursor"] is None


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"limit": "abc"}, {"cursor": "not-a-cursor"}],
)
def test_rejects_invalid_pagination_parameters(
    client: TestClient, params: dict[str, str | int]
) -> None:
    _, token_a = create_user(client, "ana@hangy.com")

    response = client.get("/users/me/blocked", params=params, headers=auth(token_a))

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/users/me/blocked")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
