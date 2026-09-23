from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.services import UserTagNotFoundError
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import TagModel
from app.infrastructure.repository.models.user_model import user_tag
from app.infrastructure.repository.user_tags import SqlAlchemyUserTagsRepository
from app.main import app

SPORTS_ID = UUID("8f2c0001-0000-4000-8000-000000000001")
WELLBEING_ID = UUID("3d100002-0000-4000-8000-000000000002")
RUNNING_ID = UUID("00000003-0000-4000-8000-000000000003")
FOOTBALL_ID = UUID("00000004-0000-4000-8000-000000000004")
YOGA_ID = UUID("00000005-0000-4000-8000-000000000005")

USER_EMAIL = "felipe@hangy.com"


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        db.add_all(
            [
                TagModel(tag_id=SPORTS_ID, tag_name="Esportes"),
                TagModel(tag_id=WELLBEING_ID, tag_name="Bem-estar"),
                TagModel(
                    tag_id=RUNNING_ID, tag_name="Corrida", tag_parent_id=SPORTS_ID
                ),
                TagModel(
                    tag_id=FOOTBALL_ID, tag_name="Futebol", tag_parent_id=SPORTS_ID
                ),
                TagModel(tag_id=YOGA_ID, tag_name="Yoga", tag_parent_id=WELLBEING_ID),
            ]
        )
        db.commit()

    def override_get_db() -> Iterator[Session]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def register_and_authenticate(client: TestClient) -> tuple[str, str]:
    register_response = client.post(
        "/register",
        json={"email": USER_EMAIL, "password": "strong-password"},
    )
    assert register_response.status_code == 201
    user_id = register_response.json()["user_id"]

    login_response = client.post(
        "/login",
        data={"username": USER_EMAIL, "password": "strong-password"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    return user_id, token


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_replacing_with_valid_micro_tags_returns_200_with_parent(
    client: TestClient,
) -> None:
    _, token = register_and_authenticate(client)

    response = client.put(
        "/users/me/tags",
        json={"tag_ids": [str(FOOTBALL_ID), str(YOGA_ID)]},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "tags": [
            {
                "id": str(FOOTBALL_ID),
                "name": "Futebol",
                "parent": {"id": str(SPORTS_ID), "name": "Esportes"},
            },
            {
                "id": str(YOGA_ID),
                "name": "Yoga",
                "parent": {"id": str(WELLBEING_ID), "name": "Bem-estar"},
            },
        ]
    }


def test_selecting_a_macro_tag_returns_400(client: TestClient) -> None:
    _, token = register_and_authenticate(client)

    response = client.put(
        "/users/me/tags",
        json={"tag_ids": [str(SPORTS_ID)]},
        headers=auth_headers(token),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Only micro tags can be selected"}


def test_unknown_tag_id_returns_404_and_writes_nothing(client: TestClient) -> None:
    user_id, token = register_and_authenticate(client)
    unknown_id = uuid4()

    response = client.put(
        "/users/me/tags",
        json={"tag_ids": [str(FOOTBALL_ID), str(unknown_id)]},
        headers=auth_headers(token),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Tag not found"}

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        rows = db.execute(
            select(user_tag.c.tag_id).where(user_tag.c.user_id == UUID(user_id))
        ).all()
    finally:
        db_generator.close()
    assert rows == []


def test_a_smaller_set_removes_tags_that_fell_out(client: TestClient) -> None:
    _, token = register_and_authenticate(client)

    first_response = client.put(
        "/users/me/tags",
        json={"tag_ids": [str(FOOTBALL_ID), str(RUNNING_ID)]},
        headers=auth_headers(token),
    )
    assert first_response.status_code == 200
    assert len(first_response.json()["tags"]) == 2

    second_response = client.put(
        "/users/me/tags",
        json={"tag_ids": [str(FOOTBALL_ID)]},
        headers=auth_headers(token),
    )

    assert second_response.status_code == 200
    assert [tag["id"] for tag in second_response.json()["tags"]] == [str(FOOTBALL_ID)]


def test_sending_the_same_set_twice_does_not_duplicate(client: TestClient) -> None:
    user_id, token = register_and_authenticate(client)
    payload = {"tag_ids": [str(FOOTBALL_ID), str(YOGA_ID)]}

    first_response = client.put(
        "/users/me/tags", json=payload, headers=auth_headers(token)
    )
    second_response = client.put(
        "/users/me/tags", json=payload, headers=auth_headers(token)
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        rows = db.execute(
            select(user_tag.c.tag_id).where(user_tag.c.user_id == UUID(user_id))
        ).all()
    finally:
        db_generator.close()
    assert len(rows) == 2


def test_replacing_tags_without_a_token_returns_401(client: TestClient) -> None:
    response = client.put(
        "/users/me/tags",
        json={"tag_ids": [str(FOOTBALL_ID)]},
    )

    assert response.status_code == 401


def test_a_tag_deleted_after_validation_fails_the_write_instead_of_dropping_it(
    client: TestClient,
) -> None:
    # Exercises the repository directly: the service already validated
    # existence before calling it, so the only way to reach this path is a
    # tag disappearing between that check and the write (a race in
    # production). The write must fail rather than silently save fewer tags
    # than the client asked for.
    user_id, _ = register_and_authenticate(client)

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        repository = SqlAlchemyUserTagsRepository(db)
        with pytest.raises(UserTagNotFoundError):
            repository.replace_user_tags(UUID(user_id), (FOOTBALL_ID, uuid4()))
    finally:
        db_generator.close()

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        rows = db.execute(
            select(user_tag.c.tag_id).where(user_tag.c.user_id == UUID(user_id))
        ).all()
    finally:
        db_generator.close()
    assert rows == []
