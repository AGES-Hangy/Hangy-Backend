from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import EventPrivacyEnum, EventStatusEnum, UserTypeEnum
from app.domain.services import UserNotFoundError, UserTagNotFoundError
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    TagModel,
    UserModel,
    event_tag,
)
from app.infrastructure.repository.models.user_model import user_tag
from app.infrastructure.repository.user_tags import SqlAlchemyUserTagsRepository
from app.main import app

SPORTS_ID = UUID("8f2c0001-0000-4000-8000-000000000001")
WELLBEING_ID = UUID("3d100002-0000-4000-8000-000000000002")
RUNNING_ID = UUID("00000003-0000-4000-8000-000000000003")
FOOTBALL_ID = UUID("00000004-0000-4000-8000-000000000004")
YOGA_ID = UUID("00000005-0000-4000-8000-000000000005")
# Deliberately inverted: ZEBRA_ID sorts before ABACATE_ID lexicographically,
# but "Abacate" sorts before "Zebra" alphabetically by name.
ZEBRA_ID = UUID("00000006-0000-4000-8000-000000000006")
ABACATE_ID = UUID("00000007-0000-4000-8000-000000000007")

USER_EMAIL = "felipe@hangy.com"
USER_PASSWORD = "strong-password"
TERMS_VERSION = "2026-08-01"


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
                TagModel(tag_id=ZEBRA_ID, tag_name="Zebra", tag_parent_id=SPORTS_ID),
                TagModel(
                    tag_id=ABACATE_ID, tag_name="Abacate", tag_parent_id=SPORTS_ID
                ),
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
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": USER_EMAIL,
            "password": USER_PASSWORD,
            "name": "Felipe",
            "cpf": "52998224725",
            "date_of_birth": "2000-01-01",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": TERMS_VERSION,
        },
    )
    assert register_response.status_code == 201
    user_id = register_response.json()["user"]["id"]

    login_response = client.post(
        "/auth/login",
        json={"email": USER_EMAIL, "password": USER_PASSWORD},
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


def test_replacing_tags_returns_them_ordered_by_name_not_by_id(
    client: TestClient,
) -> None:
    # ZEBRA_ID sorts before ABACATE_ID by id, but "Abacate" sorts before
    # "Zebra" by name: a response ordered by id (a stale post-commit reload)
    # would come back as [Zebra, Abacate] instead.
    _, token = register_and_authenticate(client)

    response = client.put(
        "/users/me/tags",
        json={"tag_ids": [str(ZEBRA_ID), str(ABACATE_ID)]},
        headers=auth_headers(token),
    )

    assert response.status_code == 200
    assert [tag["name"] for tag in response.json()["tags"]] == ["Abacate", "Zebra"]


def test_replacing_tags_for_an_account_deleted_mid_request_fails_the_write(
    client: TestClient,
) -> None:
    # A soft-deleted user is already rejected at auth time (get_current_user
    # filters deleted_at), so this exercises the repository directly: the
    # only way to reach this path is the account being deleted after auth
    # but before the write (a race in production).
    user_id, _ = register_and_authenticate(client)

    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        db.query(UserModel).filter(UserModel.user_id == UUID(user_id)).update(
            {"deleted_at": datetime.now(UTC)}
        )
        db.commit()

        repository = SqlAlchemyUserTagsRepository(db)
        with pytest.raises(UserNotFoundError):
            repository.replace_user_tags(UUID(user_id), (FOOTBALL_ID,))
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


def test_sending_more_than_the_max_allowed_tags_returns_422(
    client: TestClient,
) -> None:
    _, token = register_and_authenticate(client)
    too_many_ids = [str(uuid4()) for _ in range(21)]

    response = client.put(
        "/users/me/tags",
        json={"tag_ids": too_many_ids},
        headers=auth_headers(token),
    )

    assert response.status_code == 422


def open_db() -> Iterator[Session]:
    return app.dependency_overrides[get_db]()


def get_user_tags(client: TestClient, token: str) -> dict:
    response = client.get("/users/me/tags", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


def test_get_returns_current_tags_with_their_macro_ordered_by_macro_then_name(
    client: TestClient,
) -> None:
    _, token = register_and_authenticate(client)
    client.put(
        "/users/me/tags",
        json={"tag_ids": [str(FOOTBALL_ID), str(YOGA_ID), str(RUNNING_ID)]},
        headers=auth_headers(token),
    )

    # "Bem-estar" sorts before "Esportes", so Yoga comes first even though
    # "Corrida" and "Futebol" sort before "Yoga" by their own names.
    assert get_user_tags(client, token) == {
        "tags": [
            {
                "id": str(YOGA_ID),
                "name": "Yoga",
                "parent": {"id": str(WELLBEING_ID), "name": "Bem-estar"},
            },
            {
                "id": str(RUNNING_ID),
                "name": "Corrida",
                "parent": {"id": str(SPORTS_ID), "name": "Esportes"},
            },
            {
                "id": str(FOOTBALL_ID),
                "name": "Futebol",
                "parent": {"id": str(SPORTS_ID), "name": "Esportes"},
            },
        ]
    }


def test_get_returns_null_parent_for_a_tag_without_macro(client: TestClient) -> None:
    # The PUT only accepts micro tags, but a row pointing at a macro tag (old
    # data, or a parent deleted with ON DELETE SET NULL) must still be listed,
    # sorted under its own name.
    user_id, token = register_and_authenticate(client)
    db_generator = open_db()
    db = next(db_generator)
    try:
        for tag_id in (FOOTBALL_ID, SPORTS_ID):
            db.execute(user_tag.insert().values(user_id=UUID(user_id), tag_id=tag_id))
        db.commit()
    finally:
        db_generator.close()

    assert get_user_tags(client, token) == {
        "tags": [
            {"id": str(SPORTS_ID), "name": "Esportes", "parent": None},
            {
                "id": str(FOOTBALL_ID),
                "name": "Futebol",
                "parent": {"id": str(SPORTS_ID), "name": "Esportes"},
            },
        ]
    }


def test_get_for_a_user_without_tags_returns_an_empty_list(client: TestClient) -> None:
    _, token = register_and_authenticate(client)

    assert get_user_tags(client, token) == {"tags": []}


def test_get_without_a_token_returns_401(client: TestClient) -> None:
    response = client.get("/users/me/tags")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_get_with_an_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get("/users/me/tags", headers=auth_headers("not-a-valid-token"))

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_replacing_the_set_is_reflected_in_the_next_get(client: TestClient) -> None:
    _, token = register_and_authenticate(client)
    client.put(
        "/users/me/tags",
        json={"tag_ids": [str(FOOTBALL_ID), str(RUNNING_ID)]},
        headers=auth_headers(token),
    )

    response = client.put(
        "/users/me/tags",
        json={"tag_ids": [str(YOGA_ID), str(FOOTBALL_ID)]},
        headers=auth_headers(token),
    )
    assert response.status_code == 200

    tags = get_user_tags(client, token)["tags"]
    assert [tag["id"] for tag in tags] == [str(YOGA_ID), str(FOOTBALL_ID)]


def test_sending_the_same_set_twice_gives_the_same_get(client: TestClient) -> None:
    _, token = register_and_authenticate(client)
    payload = {"tag_ids": [str(FOOTBALL_ID), str(YOGA_ID)]}

    client.put("/users/me/tags", json=payload, headers=auth_headers(token))
    first = get_user_tags(client, token)
    client.put("/users/me/tags", json=payload, headers=auth_headers(token))
    second = get_user_tags(client, token)

    assert len(first["tags"]) == 2
    assert first == second


@pytest.mark.xfail(
    strict=True,
    reason=(
        "PUT /users/me/tags aceita lista vazia e limpa as tags (200); a US2.3 "
        "pede 400. Pendente na task 065."
    ),
)
def test_replacing_with_an_empty_list_returns_400(client: TestClient) -> None:
    _, token = register_and_authenticate(client)

    response = client.put(
        "/users/me/tags", json={"tag_ids": []}, headers=auth_headers(token)
    )

    assert response.status_code == 400


def test_the_feed_follows_the_replaced_tags(client: TestClient) -> None:
    _, token = register_and_authenticate(client)
    db_generator = open_db()
    db = next(db_generator)
    try:
        creator = UserModel(
            user_type=UserTypeEnum.PERSONAL,
            email="creator@hangy.com",
            password_hash="hashed",
        )
        db.add(creator)
        db.commit()
        starts_at = datetime.now(UTC) + timedelta(days=1)
        for title, tag_id in (("Pelada no Parcão", FOOTBALL_ID), ("Yoga", YOGA_ID)):
            event = EventModel(
                event_creator_id=creator.user_id,
                event_title=title,
                event_latitude=-30.0,
                event_longitude=-51.0,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=2),
                event_status=EventStatusEnum.PUBLISHED,
                event_privacy=EventPrivacyEnum.PUBLIC,
            )
            db.add(event)
            db.commit()
            db.execute(
                event_tag.insert().values(event_id=event.event_id, tag_id=tag_id)
            )
        db.commit()
    finally:
        db_generator.close()

    def feed_titles() -> dict[str, list[str]]:
        response = client.get("/feed", headers=auth_headers(token))
        assert response.status_code == 200, response.text
        return {
            section["tag"]["name"]: [item["title"] for item in section["items"]]
            for section in response.json()["sections"]
        }

    client.put(
        "/users/me/tags",
        json={"tag_ids": [str(FOOTBALL_ID)]},
        headers=auth_headers(token),
    )
    assert feed_titles() == {"Esportes": ["Pelada no Parcão"]}

    client.put(
        "/users/me/tags",
        json={"tag_ids": [str(YOGA_ID)]},
        headers=auth_headers(token),
    )
    assert feed_titles() == {"Bem-estar": ["Yoga"]}
