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
from app.infrastructure.repository.models import TagModel, UserModel
from app.main import app

AdminTagsClient = tuple[TestClient, sessionmaker[Session]]


@pytest.fixture
def tags_client() -> Iterator[AdminTagsClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def header_for(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def add_user(db: Session, role: UserRoleEnum) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=UserTypeEnum.PERSONAL,
            role=role,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name="Pessoa",
        )
    )
    db.commit()
    return user_id


def add_tag(db: Session, name: str, parent_id: UUID | None = None) -> UUID:
    tag_id = uuid4()
    db.add(TagModel(tag_id=tag_id, tag_name=name, tag_parent_id=parent_id))
    db.commit()
    return tag_id


def admin_headers(session_factory: sessionmaker[Session]) -> dict[str, str]:
    with session_factory() as db:
        return header_for(add_user(db, UserRoleEnum.ADMIN))


def tree_by_name(client: TestClient) -> dict[str, dict]:
    response = client.get("/tags/tree")
    assert response.status_code == 200
    return {node["name"]: node for node in response.json()}


def test_create_micro_tag_returns_201_and_appears_in_tree(
    tags_client: AdminTagsClient,
) -> None:
    client, session_factory = tags_client
    headers = admin_headers(session_factory)
    with session_factory() as db:
        category_id = add_tag(db, "Esportes")

    response = client.post(
        "/admin/tags",
        json={"name": "Escalada", "parent_id": str(category_id)},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"tag_id", "name", "parent_id", "type"}
    assert UUID(body["tag_id"])
    assert body["name"] == "Escalada"
    assert body["parent_id"] == str(category_id)
    assert body["type"] == "MICRO"
    children = tree_by_name(client)["Esportes"]["children"]
    assert children == [{"id": body["tag_id"], "name": "Escalada", "type": "MICRO"}]


def test_create_category_returns_201_and_appears_in_tree(
    tags_client: AdminTagsClient,
) -> None:
    client, session_factory = tags_client

    response = client.post(
        "/admin/tags",
        json={"name": "Vida Noturna", "parent_id": None},
        headers=admin_headers(session_factory),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Vida Noturna"
    assert body["parent_id"] is None
    assert body["type"] == "MACRO"
    node = tree_by_name(client)["Vida Noturna"]
    assert node["id"] == body["tag_id"]
    assert node["type"] == "MACRO"
    assert node["children"] == []


def test_parent_id_can_be_omitted_to_create_a_category(
    tags_client: AdminTagsClient,
) -> None:
    client, session_factory = tags_client

    response = client.post(
        "/admin/tags",
        json={"name": "Cultura"},
        headers=admin_headers(session_factory),
    )

    assert response.status_code == 201
    assert response.json()["type"] == "MACRO"


def test_name_is_trimmed_before_saving(tags_client: AdminTagsClient) -> None:
    client, session_factory = tags_client

    response = client.post(
        "/admin/tags",
        json={"name": "  Vida Noturna  ", "parent_id": None},
        headers=admin_headers(session_factory),
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Vida Noturna"


def test_duplicate_category_name_returns_409(tags_client: AdminTagsClient) -> None:
    client, session_factory = tags_client
    headers = admin_headers(session_factory)
    with session_factory() as db:
        add_tag(db, "Esportes")

    response = client.post(
        "/admin/tags", json={"name": "Esportes", "parent_id": None}, headers=headers
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Tag name already exists at this level"}
    assert len(tree_by_name(client)) == 1


def test_duplicate_micro_name_in_same_category_returns_409(
    tags_client: AdminTagsClient,
) -> None:
    client, session_factory = tags_client
    headers = admin_headers(session_factory)
    with session_factory() as db:
        category_id = add_tag(db, "Esportes")
        add_tag(db, "Escalada", category_id)

    response = client.post(
        "/admin/tags",
        json={"name": "Escalada", "parent_id": str(category_id)},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Tag name already exists at this level"}
    assert len(tree_by_name(client)["Esportes"]["children"]) == 1


def test_same_micro_name_in_another_category_is_allowed(
    tags_client: AdminTagsClient,
) -> None:
    client, session_factory = tags_client
    headers = admin_headers(session_factory)
    with session_factory() as db:
        gastronomy_id = add_tag(db, "Gastronomia")
        add_tag(db, "Bar", gastronomy_id)
        nightlife_id = add_tag(db, "Vida Noturna")

    response = client.post(
        "/admin/tags",
        json={"name": "Bar", "parent_id": str(nightlife_id)},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["parent_id"] == str(nightlife_id)


def test_micro_name_equal_to_a_category_name_is_allowed(
    tags_client: AdminTagsClient,
) -> None:
    client, session_factory = tags_client
    headers = admin_headers(session_factory)
    with session_factory() as db:
        add_tag(db, "Esportes")
        music_id = add_tag(db, "Musica")

    response = client.post(
        "/admin/tags",
        json={"name": "Esportes", "parent_id": str(music_id)},
        headers=headers,
    )

    assert response.status_code == 201


def test_parent_that_is_a_micro_tag_returns_400(tags_client: AdminTagsClient) -> None:
    client, session_factory = tags_client
    headers = admin_headers(session_factory)
    with session_factory() as db:
        category_id = add_tag(db, "Esportes")
        micro_id = add_tag(db, "Escalada", category_id)

    response = client.post(
        "/admin/tags",
        json={"name": "Boulder", "parent_id": str(micro_id)},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Parent tag is not a category"}


def test_unknown_parent_id_returns_404(tags_client: AdminTagsClient) -> None:
    client, session_factory = tags_client

    response = client.post(
        "/admin/tags",
        json={"name": "Escalada", "parent_id": str(uuid4())},
        headers=admin_headers(session_factory),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Parent tag not found"}


def test_non_admin_receives_403_and_nothing_is_created(
    tags_client: AdminTagsClient,
) -> None:
    client, session_factory = tags_client
    with session_factory() as db:
        headers = header_for(add_user(db, UserRoleEnum.USER))

    response = client.post(
        "/admin/tags", json={"name": "Vida Noturna", "parent_id": None}, headers=headers
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert tree_by_name(client) == {}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer invalid"}],
    ids=["missing token", "invalid token"],
)
def test_missing_or_invalid_token_returns_401(
    tags_client: AdminTagsClient, headers: dict[str, str]
) -> None:
    client, _ = tags_client

    response = client.post(
        "/admin/tags", json={"name": "Vida Noturna", "parent_id": None}, headers=headers
    )

    assert response.status_code == 401


@pytest.mark.parametrize(
    "name",
    ["", "   ", "x" * 51],
    ids=["empty", "blank", "too long"],
)
def test_invalid_name_returns_422(tags_client: AdminTagsClient, name: str) -> None:
    client, session_factory = tags_client

    response = client.post(
        "/admin/tags",
        json={"name": name, "parent_id": None},
        headers=admin_headers(session_factory),
    )

    assert response.status_code == 422


def test_name_at_the_length_limit_is_accepted(tags_client: AdminTagsClient) -> None:
    client, session_factory = tags_client

    response = client.post(
        "/admin/tags",
        json={"name": "x" * 50, "parent_id": None},
        headers=admin_headers(session_factory),
    )

    assert response.status_code == 201


def test_malformed_parent_id_returns_422(tags_client: AdminTagsClient) -> None:
    client, session_factory = tags_client

    response = client.post(
        "/admin/tags",
        json={"name": "Escalada", "parent_id": "not-a-uuid"},
        headers=admin_headers(session_factory),
    )

    assert response.status_code == 422
