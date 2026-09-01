from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import TagTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import TagModel
from app.main import app

SPORTS_ID = UUID("8f2c0001-0000-4000-8000-000000000001")
WELLBEING_ID = UUID("3d100002-0000-4000-8000-000000000002")
RUNNING_ID = UUID("00000003-0000-4000-8000-000000000003")
FOOTBALL_ID = UUID("00000004-0000-4000-8000-000000000004")
YOGA_ID = UUID("00000005-0000-4000-8000-000000000005")


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


def test_without_a_filter_returns_every_tag(client: TestClient) -> None:
    response = client.get("/tags")

    assert response.status_code == 200
    assert [tag["name"] for tag in response.json()] == [
        "Bem-estar",
        "Corrida",
        "Esportes",
        "Futebol",
        "Yoga",
    ]


def test_type_macro_returns_only_macro_tags_with_a_null_parent(
    client: TestClient,
) -> None:
    response = client.get("/tags", params={"type": "MACRO"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(WELLBEING_ID),
            "name": "Bem-estar",
            "type": "MACRO",
            "parent_id": None,
        },
        {
            "id": str(SPORTS_ID),
            "name": "Esportes",
            "type": "MACRO",
            "parent_id": None,
        },
    ]


def test_type_micro_returns_only_micro_tags(client: TestClient) -> None:
    response = client.get("/tags", params={"type": "MICRO"})

    assert response.status_code == 200
    body = response.json()
    assert [tag["name"] for tag in body] == ["Corrida", "Futebol", "Yoga"]
    assert all(tag["type"] == "MICRO" for tag in body)
    assert all(tag["parent_id"] is not None for tag in body)


def test_parent_id_returns_only_the_micro_tags_of_that_macro(
    client: TestClient,
) -> None:
    response = client.get("/tags", params={"parent_id": str(SPORTS_ID)})

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(RUNNING_ID),
            "name": "Corrida",
            "type": "MICRO",
            "parent_id": str(SPORTS_ID),
        },
        {
            "id": str(FOOTBALL_ID),
            "name": "Futebol",
            "type": "MICRO",
            "parent_id": str(SPORTS_ID),
        },
    ]


def test_an_unknown_parent_id_returns_404(client: TestClient) -> None:
    response = client.get("/tags", params={"parent_id": str(uuid4())})

    assert response.status_code == 404
    assert response.json() == {"detail": "Tag not found"}


def test_a_micro_tag_as_parent_returns_404(client: TestClient) -> None:
    # The tree has exactly two levels, so a micro tag is never a parent.
    response = client.get("/tags", params={"parent_id": str(YOGA_ID)})

    assert response.status_code == 404
    assert response.json() == {"detail": "Tag not found"}


def test_combining_type_and_parent_id_returns_400(client: TestClient) -> None:
    response = client.get(
        "/tags",
        params={"type": "MACRO", "parent_id": str(SPORTS_ID)},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid tag filter"}


def test_an_unknown_type_returns_400(client: TestClient) -> None:
    response = client.get("/tags", params={"type": "GIGA"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid tag filter"}


def test_a_malformed_parent_id_returns_400(client: TestClient) -> None:
    response = client.get("/tags", params={"parent_id": "not-a-uuid"})

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid tag filter"}


def test_openapi_documents_the_tag_listing(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/tags"]["get"]

    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "type",
        "parent_id",
    ]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "type": "array",
        "items": {"$ref": "#/components/schemas/TagOutput"},
        "title": "Response List Tags Tags Get",
    }
