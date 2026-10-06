from __future__ import annotations

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
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.event_participant_model import (
    EventParticipantModel,
)
from app.main import app

URL = "/users/me/events"


@pytest.fixture
def events_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_token(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=30)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def create_user(db: Session) -> UserModel:
    user = UserModel(
        user_id=uuid4(),
        user_type=UserTypeEnum.PERSONAL,
        role=UserRoleEnum.USER,
        email=f"{uuid4()}@test.com",
        password_hash="hashed",
        name="Test User",
    )
    db.add(user)
    db.flush()
    return user


def create_event(
    db: Session,
    creator_id: UUID,
    title: str,
    *,
    starts_at: datetime,
    ends_at: datetime | None = None,
    event_status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    event_id: UUID | None = None,
    deleted_at: datetime | None = None,
) -> EventModel:
    event = EventModel(
        event_id=event_id or uuid4(),
        event_creator_id=creator_id,
        event_title=title,
        location_name="Parcão",
        cover_photo_url="https://example.com/cover.jpg",
        event_latitude=0.0,
        event_longitude=0.0,
        starts_at=starts_at,
        ends_at=ends_at or starts_at + timedelta(hours=2),
        event_status=event_status,
        event_privacy=EventPrivacyEnum.PUBLIC,
        deleted_at=deleted_at,
    )
    db.add(event)
    db.flush()
    return event


def join(
    db: Session,
    user_id: UUID,
    event: EventModel,
    status: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> None:
    db.add(
        EventParticipantModel(user_id=user_id, event_id=event.event_id, status=status)
    )
    db.flush()


def titles(response) -> list[str]:
    return [item["title"] for item in response.json()["items"]]


NOW = datetime.now(UTC)


def test_confirmed_tab_lists_only_upcoming_confirmed_events(events_client) -> None:
    client, session = events_client
    with session() as db:
        me = create_user(db)
        other = create_user(db)
        upcoming = create_event(
            db, other.user_id, "upcoming", starts_at=NOW + timedelta(days=2)
        )
        join(db, me.user_id, upcoming)
        in_progress = create_event(
            db,
            other.user_id,
            "in progress",
            starts_at=NOW - timedelta(hours=1),
            ends_at=NOW + timedelta(hours=1),
        )
        join(db, me.user_id, in_progress)
        pending = create_event(
            db, other.user_id, "pending", starts_at=NOW + timedelta(days=3)
        )
        join(db, me.user_id, pending, EventParticipantStatusEnum.PENDING)
        cancelled_part = create_event(
            db, other.user_id, "cancelled part.", starts_at=NOW + timedelta(days=3)
        )
        join(db, me.user_id, cancelled_part, EventParticipantStatusEnum.CANCELLED)
        cancelled_event = create_event(
            db,
            other.user_id,
            "cancelled event",
            starts_at=NOW + timedelta(days=3),
            event_status=EventStatusEnum.CANCELLED,
        )
        join(db, me.user_id, cancelled_event)
        deleted = create_event(
            db,
            other.user_id,
            "deleted",
            starts_at=NOW + timedelta(days=3),
            deleted_at=NOW,
        )
        join(db, me.user_id, deleted)
        over = create_event(
            db, other.user_id, "over", starts_at=NOW - timedelta(days=2)
        )
        join(db, me.user_id, over)
        not_mine = create_event(
            db, other.user_id, "not mine", starts_at=NOW + timedelta(days=4)
        )
        join(db, other.user_id, not_mine)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params={"tab": "confirmed"}, headers=headers)

    assert response.status_code == 200
    assert titles(response) == ["in progress", "upcoming"]
    assert response.json()["next_cursor"] is None


def test_past_tab_lists_only_finished_events_with_participation(events_client) -> None:
    client, session = events_client
    with session() as db:
        me = create_user(db)
        other = create_user(db)
        elapsed = create_event(
            db, other.user_id, "elapsed", starts_at=NOW - timedelta(days=3)
        )
        join(db, me.user_id, elapsed)
        closed_early = create_event(
            db,
            other.user_id,
            "closed early",
            starts_at=NOW - timedelta(days=1),
            ends_at=NOW + timedelta(days=1),
            event_status=EventStatusEnum.FINISHED,
        )
        join(db, me.user_id, closed_early)
        upcoming = create_event(
            db, other.user_id, "upcoming", starts_at=NOW + timedelta(days=1)
        )
        join(db, me.user_id, upcoming)
        cancelled_event = create_event(
            db,
            other.user_id,
            "cancelled",
            starts_at=NOW - timedelta(days=5),
            event_status=EventStatusEnum.CANCELLED,
        )
        join(db, me.user_id, cancelled_event)
        deleted = create_event(
            db,
            other.user_id,
            "deleted",
            starts_at=NOW - timedelta(days=5),
            deleted_at=NOW,
        )
        join(db, me.user_id, deleted)
        pending = create_event(
            db, other.user_id, "pending", starts_at=NOW - timedelta(days=6)
        )
        join(db, me.user_id, pending, EventParticipantStatusEnum.PENDING)
        not_mine = create_event(
            db, other.user_id, "not mine", starts_at=NOW - timedelta(days=7)
        )
        join(db, other.user_id, not_mine)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params={"tab": "past"}, headers=headers)

    assert response.status_code == 200
    assert titles(response) == ["closed early", "elapsed"]


def test_event_item_has_the_documented_shape(events_client) -> None:
    client, session = events_client
    starts_at = NOW + timedelta(days=1)
    with session() as db:
        me = create_user(db)
        event = create_event(db, me.user_id, "Pelada no Parcão", starts_at=starts_at)
        join(db, me.user_id, event)
        db.commit()
        headers = make_token(me.user_id)
        event_id = str(event.event_id)

    body = client.get(URL, params={"tab": "confirmed"}, headers=headers).json()

    [item] = body["items"]
    assert set(item) == {
        "event_id",
        "title",
        "event_date",
        "location_name",
        "cover_photo_url",
        "participation_status",
    }
    assert item["event_id"] == event_id
    assert item["title"] == "Pelada no Parcão"
    assert item["location_name"] == "Parcão"
    assert item["cover_photo_url"] == "https://example.com/cover.jpg"
    assert item["participation_status"] == "CONFIRMED"
    assert datetime.fromisoformat(item["event_date"]).replace(tzinfo=UTC) == starts_at
    assert body["next_cursor"] is None


def test_tabs_are_ordered_by_date_regardless_of_id_order(events_client) -> None:
    client, session = events_client
    with session() as db:
        me = create_user(db)
        ids = sorted(uuid4() for _ in range(3))
        for index, event_id in enumerate(ids):
            upcoming = create_event(
                db,
                me.user_id,
                f"up{index}",
                starts_at=NOW + timedelta(days=3 - index),
                event_id=event_id,
            )
            join(db, me.user_id, upcoming)
        past_ids = sorted(uuid4() for _ in range(3))
        for index, event_id in enumerate(past_ids):
            past = create_event(
                db,
                me.user_id,
                f"past{index}",
                starts_at=NOW - timedelta(days=3 - index),
                event_id=event_id,
            )
            join(db, me.user_id, past)
        db.commit()
        headers = make_token(me.user_id)

    confirmed = client.get(URL, params={"tab": "confirmed"}, headers=headers)
    past = client.get(URL, params={"tab": "past"}, headers=headers)

    assert titles(confirmed) == ["up2", "up1", "up0"]
    assert titles(past) == ["past2", "past1", "past0"]


@pytest.mark.parametrize("tab", ["confirmed", "past"])
def test_pagination_walks_every_item_once_even_with_equal_dates(
    events_client, tab: str
) -> None:
    client, session = events_client
    shared = (
        (NOW + timedelta(days=2)) if tab == "confirmed" else (NOW - timedelta(days=2))
    )
    with session() as db:
        me = create_user(db)
        expected: set[str] = set()
        for index in range(7):
            starts_at = shared + timedelta(hours=index // 2)
            event = create_event(db, me.user_id, f"e{index}", starts_at=starts_at)
            join(db, me.user_id, event)
            expected.add(str(event.event_id))
        db.commit()
        headers = make_token(me.user_id)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"tab": tab, "limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = client.get(URL, params=params, headers=headers).json()
        seen += [item["event_id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == 7
    assert set(seen) == expected


def test_exact_page_size_returns_no_next_cursor(events_client) -> None:
    client, session = events_client
    with session() as db:
        me = create_user(db)
        for index in range(2):
            event = create_event(
                db, me.user_id, f"e{index}", starts_at=NOW + timedelta(days=index + 1)
            )
            join(db, me.user_id, event)
        db.commit()
        headers = make_token(me.user_id)

    body = client.get(
        URL, params={"tab": "confirmed", "limit": 2}, headers=headers
    ).json()

    assert len(body["items"]) == 2
    assert body["next_cursor"] is None


@pytest.mark.parametrize("tab", ["confirmed", "past"])
def test_empty_tab_returns_empty_page(events_client, tab: str) -> None:
    client, session = events_client
    with session() as db:
        me = create_user(db)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params={"tab": tab}, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("tab", ["photos", "CONFIRMED", ""])
def test_invalid_tab_returns_400(events_client, tab: str) -> None:
    client, session = events_client
    with session() as db:
        me = create_user(db)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params={"tab": tab}, headers=headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid tab"}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"cursor": "not-a-valid-cursor"},
    ],
)
def test_invalid_pagination_returns_400(events_client, params: dict) -> None:
    client, session = events_client
    with session() as db:
        me = create_user(db)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params={"tab": "confirmed", **params}, headers=headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_missing_token_returns_401(events_client) -> None:
    client, _ = events_client

    response = client.get(URL, params={"tab": "confirmed"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_invalid_token_returns_401(events_client) -> None:
    client, _ = events_client

    response = client.get(
        URL, params={"tab": "confirmed"}, headers={"Authorization": "Bearer garbage"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}