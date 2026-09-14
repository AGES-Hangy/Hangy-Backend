from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
from app.main import app
from app.seed import SEED_TAGS, seed_tags


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


def run_seed_tags() -> None:
    db_generator = app.dependency_overrides[get_db]()
    db = next(db_generator)
    try:
        seed_tags(db)
    finally:
        db_generator.close()


def test_tags_tree_returns_macros_with_nested_micros(client: TestClient) -> None:
    run_seed_tags()

    response = client.get("/tags/tree")

    assert response.status_code == 200
    by_name = {macro["name"]: macro for macro in response.json()}
    assert set(by_name) == set(SEED_TAGS)
    for macro_name, micro_names in SEED_TAGS.items():
        assert by_name[macro_name]["type"] == "MACRO"
        children = {child["name"] for child in by_name[macro_name]["children"]}
        assert children == set(micro_names)
