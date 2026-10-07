from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event, insert, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserConnectionStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository import user_profile as user_profile_repository
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
    UserModel,
    user_tag,
)
from app.infrastructure.repository.models.event_experience_model import (
    EventExperienceModel,
)
from app.infrastructure.repository.models.experience_images_model import (
    ExperienceImagesModel,
)
from app.infrastructure.repository.models.user_connection_model import (
    UserConnectionModel,
)
from app.infrastructure.repository.user_profile import SqlAlchemyUserProfileRepository
from app.main import app

USER_EMAIL = "ana@hangy.com"
USER_PASSWORD = "strong-password"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

CONFIRMED = EventParticipantStatusEnum.CONFIRMED


@dataclass
class Context:
    client: TestClient
    db: Session
    engine: Engine


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Context]:
    # Pins the clock the counters compare against, so the time boundary is exact.
    monkeypatch.setattr(user_profile_repository, "_now_utc", lambda: NOW)
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
        yield Context(client=test_client, db=db, engine=engine)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def register_and_login(client: TestClient) -> tuple[UUID, dict[str, str]]:
    """Register a personal user and return (user_id, auth headers)."""
    reg = client.post(
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
    assert reg.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": USER_EMAIL, "password": USER_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return UUID(reg.json()["user"]["id"]), {"Authorization": f"Bearer {token}"}


def get_counts(client: TestClient, headers: dict[str, str]) -> dict[str, int]:
    response = client.get("/users/me/profile", headers=headers)
    assert response.status_code == 200
    return response.json()["counts"]


def _add_user(db: Session, email: str) -> UserModel:
    user = UserModel(
        user_id=uuid4(),
        user_type=UserTypeEnum.PERSONAL,
        role=UserRoleEnum.USER,
        email=email,
        password_hash="x",
        name=email,
    )
    db.add(user)
    db.flush()
    return user


def _add_event(
    db: Session,
    creator_id: UUID,
    *,
    starts_at: datetime,
    ends_at: datetime,
    status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    deleted_at: datetime | None = None,
) -> EventModel:
    model = EventModel(
        event_id=uuid4(),
        event_creator_id=creator_id,
        event_title="Test event",
        event_latitude=0.0,
        event_longitude=0.0,
        starts_at=starts_at,
        ends_at=ends_at,
        event_status=status,
        event_privacy=EventPrivacyEnum.PUBLIC,
        deleted_at=deleted_at,
    )
    db.add(model)
    db.flush()
    return model


def _future_event(db: Session, creator_id: UUID, **kwargs) -> EventModel:
    return _add_event(
        db,
        creator_id,
        starts_at=NOW + timedelta(days=1),
        ends_at=NOW + timedelta(days=1, hours=3),
        **kwargs,
    )


def _ended_event(db: Session, creator_id: UUID, **kwargs) -> EventModel:
    return _add_event(
        db,
        creator_id,
        starts_at=NOW - timedelta(days=1, hours=3),
        ends_at=NOW - timedelta(days=1),
        **kwargs,
    )


def _participate(
    db: Session,
    user_id: UUID,
    event_id: UUID,
    status: EventParticipantStatusEnum = CONFIRMED,
) -> EventParticipantModel:
    model = EventParticipantModel(
        participant_id=uuid4(), user_id=user_id, event_id=event_id, status=status
    )
    db.add(model)
    db.flush()
    return model


def _add_photo(
    db: Session,
    participant_id: UUID,
    *,
    deleted_at: datetime | None = None,
    experience_deleted_at: datetime | None = None,
) -> None:
    experience = db.scalar(
        select(EventExperienceModel).where(
            EventExperienceModel.event_participant_id == participant_id
        )
    )
    if experience is None:
        experience = EventExperienceModel(
            experience_id=uuid4(),
            event_participant_id=participant_id,
            description="nice event",
            deleted_at=experience_deleted_at,
        )
        db.add(experience)
        db.flush()
    db.add(
        ExperienceImagesModel(
            photo_id=uuid4(),
            experience_id=experience.experience_id,
            photo_url="https://cdn.example.com/img.jpg",
            deleted_at=deleted_at,
        )
    )
    db.flush()


def _connect(
    db: Session,
    requester_id: UUID,
    receiver_id: UUID,
    status: UserConnectionStatusEnum = UserConnectionStatusEnum.CONFIRMED,
    deleted_at: datetime | None = None,
) -> None:
    db.add(
        UserConnectionModel(
            requester_id=requester_id,
            receiver_id=receiver_id,
            status=status,
            deleted_at=deleted_at,
        )
    )
    db.flush()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_missing_token_returns_401(ctx: Context) -> None:
    response = ctx.client.get("/users/me/profile")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_invalid_token_returns_401(ctx: Context) -> None:
    response = ctx.client.get(
        "/users/me/profile", headers={"Authorization": "Bearer invalid"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_deleted_account_returns_403(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    ctx.db.get(UserModel, user_id).deleted_at = NOW
    ctx.db.commit()

    response = ctx.client.get("/users/me/profile", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Account has been deleted"}


def test_openapi_documents_success_and_auth_errors(ctx: Context) -> None:
    operation = ctx.client.get("/openapi.json").json()["paths"]["/users/me/profile"][
        "get"
    ]

    assert set(operation["responses"]) == {"200", "401", "403"}


# ---------------------------------------------------------------------------
# Profile data
# ---------------------------------------------------------------------------


def test_new_user_gets_profile_with_empty_tabs(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)

    response = ctx.client.get("/users/me/profile", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "profile": {
            "id": str(user_id),
            "name": "Ana Souza",
            "description": None,
            "photo_url": None,
            "tags": [],
            "connections_count": 0,
        },
        "counts": {"past": 0, "confirmed": 0, "photos": 0},
    }


def test_profile_exposes_description_and_photo(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    user = ctx.db.get(UserModel, user_id)
    user.description = "bio"
    user.profile_photo_url = "https://cdn.example.com/ana.jpg"
    ctx.db.commit()

    profile = ctx.client.get("/users/me/profile", headers=headers).json()["profile"]

    assert profile["description"] == "bio"
    assert profile["photo_url"] == "https://cdn.example.com/ana.jpg"


def test_tags_follow_macro_then_name_order(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    # UUID order (Rock, Futebol, Corrida) differs from the expected display order.
    sports = TagModel(tag_id=UUID(int=10), tag_name="Esportes")
    music = TagModel(tag_id=UUID(int=11), tag_name="Musica")
    rock = TagModel(tag_id=UUID(int=1), tag_name="Rock", tag_parent_id=music.tag_id)
    football = TagModel(
        tag_id=UUID(int=2), tag_name="Futebol", tag_parent_id=sports.tag_id
    )
    running = TagModel(
        tag_id=UUID(int=3), tag_name="Corrida", tag_parent_id=sports.tag_id
    )
    ctx.db.add_all([sports, music])
    ctx.db.flush()
    ctx.db.add_all([rock, football, running])
    ctx.db.flush()
    ctx.db.execute(
        insert(user_tag),
        [
            {"user_id": user_id, "tag_id": tag.tag_id}
            for tag in (rock, football, running)
        ],
    )
    ctx.db.commit()

    tags = ctx.client.get("/users/me/profile", headers=headers).json()["profile"][
        "tags"
    ]

    assert tags == [
        {"id": str(running.tag_id), "name": "Corrida"},
        {"id": str(football.tag_id), "name": "Futebol"},
        {"id": str(rock.tag_id), "name": "Rock"},
    ]


def test_connections_count_only_confirmed_active_in_both_directions(
    ctx: Context,
) -> None:
    user_id, headers = register_and_login(ctx.client)
    friends = [_add_user(ctx.db, f"friend{i}@hangy.com") for i in range(5)]
    _connect(ctx.db, user_id, friends[0].user_id)
    _connect(ctx.db, friends[1].user_id, user_id)
    _connect(ctx.db, user_id, friends[2].user_id, UserConnectionStatusEnum.PENDING)
    _connect(ctx.db, friends[3].user_id, user_id, UserConnectionStatusEnum.REJECTED)
    _connect(ctx.db, user_id, friends[4].user_id, deleted_at=NOW)
    # A connection between two other users is not ours.
    _connect(ctx.db, friends[0].user_id, friends[1].user_id)
    ctx.db.commit()

    profile = ctx.client.get("/users/me/profile", headers=headers).json()["profile"]

    assert profile["connections_count"] == 2


# ---------------------------------------------------------------------------
# Tab counters
# ---------------------------------------------------------------------------


def test_confirmed_counts_future_and_past_counts_ended(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    _participate(ctx.db, user_id, _future_event(ctx.db, user_id).event_id)
    _participate(ctx.db, user_id, _future_event(ctx.db, user_id).event_id)
    _participate(ctx.db, user_id, _ended_event(ctx.db, user_id).event_id)
    ctx.db.commit()

    assert get_counts(ctx.client, headers) == {"past": 1, "confirmed": 2, "photos": 0}


def test_event_in_progress_is_still_confirmed(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    ongoing = _add_event(
        ctx.db,
        user_id,
        starts_at=NOW - timedelta(hours=1),
        ends_at=NOW + timedelta(hours=1),
    )
    _participate(ctx.db, user_id, ongoing.event_id)
    ctx.db.commit()

    assert get_counts(ctx.client, headers) == {"past": 0, "confirmed": 1, "photos": 0}


def test_event_ending_exactly_now_is_past(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    boundary = _add_event(
        ctx.db, user_id, starts_at=NOW - timedelta(hours=3), ends_at=NOW
    )
    _participate(ctx.db, user_id, boundary.event_id)
    ctx.db.commit()

    assert get_counts(ctx.client, headers) == {"past": 1, "confirmed": 0, "photos": 0}


def test_elapsed_event_without_status_change_is_past(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    # Still PUBLISHED: nobody flipped it to FINISHED, but ends_at has passed.
    _participate(ctx.db, user_id, _ended_event(ctx.db, user_id).event_id)
    ctx.db.commit()

    assert get_counts(ctx.client, headers)["past"] == 1


def test_finished_event_is_past_even_before_ends_at(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    finished = _future_event(ctx.db, user_id, status=EventStatusEnum.FINISHED)
    _participate(ctx.db, user_id, finished.event_id)
    ctx.db.commit()

    assert get_counts(ctx.client, headers) == {"past": 1, "confirmed": 0, "photos": 0}


@pytest.mark.parametrize(
    "event_status", [EventStatusEnum.CANCELLED, EventStatusEnum.DRAFT]
)
def test_cancelled_or_draft_events_are_in_no_tab(
    ctx: Context, event_status: EventStatusEnum
) -> None:
    user_id, headers = register_and_login(ctx.client)
    future = _future_event(ctx.db, user_id, status=event_status)
    ended = _ended_event(ctx.db, user_id, status=event_status)
    _participate(ctx.db, user_id, future.event_id)
    _participate(ctx.db, user_id, ended.event_id)
    ctx.db.commit()

    assert get_counts(ctx.client, headers) == {"past": 0, "confirmed": 0, "photos": 0}


def test_deleted_events_are_in_no_tab(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    _participate(
        ctx.db, user_id, _future_event(ctx.db, user_id, deleted_at=NOW).event_id
    )
    _participate(
        ctx.db, user_id, _ended_event(ctx.db, user_id, deleted_at=NOW).event_id
    )
    ctx.db.commit()

    assert get_counts(ctx.client, headers) == {"past": 0, "confirmed": 0, "photos": 0}


@pytest.mark.parametrize(
    "participant_status",
    [
        EventParticipantStatusEnum.PENDING,
        EventParticipantStatusEnum.REJECTED,
        EventParticipantStatusEnum.CANCELLED,
        EventParticipantStatusEnum.REMOVED,
    ],
)
def test_only_confirmed_participations_are_counted(
    ctx: Context, participant_status: EventParticipantStatusEnum
) -> None:
    user_id, headers = register_and_login(ctx.client)
    future = _future_event(ctx.db, user_id)
    ended = _ended_event(ctx.db, user_id)
    _participate(ctx.db, user_id, future.event_id, participant_status)
    _participate(ctx.db, user_id, ended.event_id, participant_status)
    ctx.db.commit()

    assert get_counts(ctx.client, headers) == {"past": 0, "confirmed": 0, "photos": 0}


def test_other_users_participations_are_not_counted(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    other = _add_user(ctx.db, "other@hangy.com")
    _participate(ctx.db, other.user_id, _future_event(ctx.db, user_id).event_id)
    _participate(ctx.db, other.user_id, _ended_event(ctx.db, user_id).event_id)
    ctx.db.commit()

    assert get_counts(ctx.client, headers) == {"past": 0, "confirmed": 0, "photos": 0}


def test_photos_count_only_active_images_of_the_user(ctx: Context) -> None:
    user_id, headers = register_and_login(ctx.client)
    other = _add_user(ctx.db, "other@hangy.com")
    event_id = _ended_event(ctx.db, user_id).event_id
    mine = _participate(ctx.db, user_id, event_id)
    theirs = _participate(ctx.db, other.user_id, event_id)
    deleted_event_id = _ended_event(ctx.db, user_id).event_id
    mine_with_deleted_experience = _participate(ctx.db, user_id, deleted_event_id)
    _add_photo(ctx.db, mine.participant_id)
    _add_photo(ctx.db, mine.participant_id)
    _add_photo(ctx.db, mine.participant_id, deleted_at=NOW)
    _add_photo(
        ctx.db, mine_with_deleted_experience.participant_id, experience_deleted_at=NOW
    )
    _add_photo(ctx.db, theirs.participant_id)
    ctx.db.commit()

    assert get_counts(ctx.client, headers)["photos"] == 2


def test_counts_are_aggregated_in_a_single_query(ctx: Context) -> None:
    user_id, _ = register_and_login(ctx.client)
    statements: list[str] = []

    def record(conn, cursor, statement, *args) -> None:
        statements.append(statement)

    event.listen(ctx.engine, "before_cursor_execute", record)
    try:
        counts = SqlAlchemyUserProfileRepository(ctx.db).get_profile_counts(user_id)
    finally:
        event.remove(ctx.engine, "before_cursor_execute", record)

    assert len(statements) == 1
    assert (counts.past, counts.confirmed, counts.photos, counts.connections) == (
        0,
        0,
        0,
        0,
    )
