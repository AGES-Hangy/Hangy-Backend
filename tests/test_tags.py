from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import TagTypeEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import TagModel
from app.main import app


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


def seed_tags() -> None:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        sports = TagModel(tag_name="Esportes", tag_type=TagTypeEnum.MACRO)
        db.add(sports)
        db.flush()
        db.add(
            TagModel(
                tag_name="Futebol",
                tag_type=TagTypeEnum.MICRO,
                tag_parent_id=sports.tag_id,
            )
        )
        db.add(
            TagModel(
                tag_name="Corrida",
                tag_type=TagTypeEnum.MICRO,
                tag_parent_id=sports.tag_id,
            )
        )
        db.add(TagModel(tag_name="Música", tag_type=TagTypeEnum.MACRO))
        db.commit()
    finally:
        db_generator.close()


def test_tags_tree_returns_macros_with_nested_micros(client: TestClient) -> None:
    seed_tags()

    response = client.get("/tags/tree")

    assert response.status_code == 200
    by_name = {macro["name"]: macro for macro in response.json()}
    assert by_name["Esportes"]["type"] == "MACRO"
    assert {c["name"] for c in by_name["Esportes"]["children"]} == {
        "Futebol",
        "Corrida",
    }
    assert by_name["Música"]["children"] == []
