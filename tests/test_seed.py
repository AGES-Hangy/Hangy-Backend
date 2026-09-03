from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
    UserModel,
    user_tag,
)
from app.main import app
from app.seed import (
    SEED_EVENTS,
    SEED_TAGS,
    SEED_USERS,
    seed_events,
    seed_tags,
    seed_user_interests,
    seed_users,
)

# Every macro tag plus the micro tags that hang below it.
SEED_TAG_COUNT = len(SEED_TAGS) + sum(len(micros) for micros in SEED_TAGS.values())


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed_everything(db: Session) -> None:
    seed_users(db)
    seed_tags(db)
    seed_user_interests(db)
    seed_events(db)


def count(db: Session, entity: object) -> int:
    return db.scalar(select(func.count()).select_from(entity))


def test_seed_creates_the_sample_data_only_once(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        seed_everything(db)

        users = db.scalars(select(UserModel).order_by(UserModel.email)).all()
        tags = db.scalars(select(TagModel.tag_name)).all()

        assert [user.email for user in users] == sorted(
            credentials.email for credentials in SEED_USERS
        )
        assert all(user.password_hash for user in users)
        assert len(tags) == SEED_TAG_COUNT
        assert count(db, EventModel) == len(SEED_EVENTS)
        assert count(db, user_tag) == 4
        assert count(db, EventParticipantModel) == 6


def test_seed_tags_creates_the_default_macro_and_micro_tags_only_once(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_tags(db)
        seed_tags(db)

        macros = db.scalars(
            select(TagModel).where(TagModel.tag_parent_id.is_(None))
        ).all()

        assert sorted(macro.tag_name for macro in macros) == sorted(SEED_TAGS)

        for macro in macros:
            micro_names = db.scalars(
                select(TagModel.tag_name).where(TagModel.tag_parent_id == macro.tag_id)
            ).all()
            assert sorted(micro_names) == sorted(SEED_TAGS[macro.tag_name])


def test_seed_hangs_every_micro_tag_below_a_macro_tag(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

        football = db.scalar(select(TagModel).where(TagModel.tag_name == "Futebol"))

        assert football is not None
        assert football.parent is not None
        assert football.parent.tag_name == "Esportes"
        assert football.parent.tag_parent_id is None


def test_seeded_feed_matches_the_documented_sample(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "user@hangy.com", "password": "user-password"},
        )
        assert login.status_code == 200
        response = client.get(
            "/feed",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    sections = response.json()["sections"]
    assert [section["tag"]["name"] for section in sections] == ["Esportes", "Música"]

    sports = [
        (item["title"], item["participants_count"], item["event_date"] is None)
        for item in sections[0]["items"]
    ]
    assert sports == [
        ("Pelada no Parcão", 2, False),
        # PRIVATE: discoverable, but the schedule stays hidden.
        ("Aniversário da Maria", 0, True),
        ("Corrida da Redenção", 1, False),
    ]
    assert [item["title"] for item in sections[1]["items"]] == [
        "Show de rock no Opinião"
    ]


def test_seeded_business_user_has_an_empty_feed(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/login",
            data={"username": "admin@hangy.com", "password": "admin-password"},
        )
        response = client.get(
            "/feed",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    app.dependency_overrides.clear()

    assert response.json() == {"sections": []}
