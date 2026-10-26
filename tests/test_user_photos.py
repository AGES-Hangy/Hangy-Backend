"""Tests for GET /users/me/photos and GET /users/{user_id}/photos.

Follows the pattern from tests/test_auth.py:
- SQLite in-memory with StaticPool
- Manually minted JWTs to avoid round-tripping /register
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserConnectionStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    UserBlockModel,
    UserConnectionModel,
    UserModel,
)
from app.infrastructure.repository.models.event_experience_model import (
    EventExperienceModel,
)
from app.infrastructure.repository.models.experience_images_model import (
    ExperienceImagesModel,
)
from app.main import app

URL = "/users/me/photos"
NOW = datetime.now(UTC)


@pytest.fixture
def photos_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


def create_event(db: Session, creator_id: UUID, title: str) -> EventModel:
    event = EventModel(
        event_id=uuid4(),
        event_creator_id=creator_id,
        event_title=title,
        event_latitude=0.0,
        event_longitude=0.0,
        starts_at=NOW - timedelta(days=2),
        ends_at=NOW - timedelta(days=2) + timedelta(hours=2),
        event_status=EventStatusEnum.FINISHED,
        event_privacy=EventPrivacyEnum.PUBLIC,
    )
    db.add(event)
    db.flush()
    return event


def create_experience(
    db: Session,
    user_id: UUID,
    event: EventModel,
    *,
    deleted_at: datetime | None = None,
) -> EventExperienceModel:
    participant = db.scalar(
        select(EventParticipantModel).where(
            EventParticipantModel.user_id == user_id,
            EventParticipantModel.event_id == event.event_id,
        )
    )
    if participant is None:
        participant = EventParticipantModel(
            user_id=user_id,
            event_id=event.event_id,
            status=EventParticipantStatusEnum.CONFIRMED,
        )
        db.add(participant)
        db.flush()
    experience = EventExperienceModel(
        experience_id=uuid4(),
        event_participant_id=participant.participant_id,
        description="Foi demais",
        deleted_at=deleted_at,
    )
    db.add(experience)
    db.flush()
    return experience


def add_photo(
    db: Session,
    experience: EventExperienceModel,
    url: str,
    *,
    created_at: datetime,
    photo_id: UUID | None = None,
    deleted_at: datetime | None = None,
) -> ExperienceImagesModel:
    image = ExperienceImagesModel(
        photo_id=photo_id or uuid4(),
        experience_id=experience.experience_id,
        photo_url=url,
        created_at=created_at,
        deleted_at=deleted_at,
    )
    db.add(image)
    db.flush()
    return image


def urls(response) -> list[str]:
    return [item["photo_url"] for item in response.json()["items"]]


def test_lists_only_the_users_own_photos(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        other = create_user(db)
        event = create_event(db, other.user_id, "Pelada no Parcão")
        mine = create_experience(db, me.user_id, event)
        add_photo(db, mine, "https://img/mine.jpg", created_at=NOW)
        theirs = create_experience(db, other.user_id, event)
        add_photo(db, theirs, "https://img/theirs.jpg", created_at=NOW)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, headers=headers)

    assert response.status_code == 200
    assert urls(response) == ["https://img/mine.jpg"]
    assert response.json()["next_cursor"] is None


def test_deleted_photos_and_experiences_are_left_out(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        event = create_event(db, me.user_id, "Pelada no Parcão")
        live = create_experience(db, me.user_id, event)
        add_photo(db, live, "https://img/live.jpg", created_at=NOW)
        add_photo(
            db, live, "https://img/deleted-photo.jpg", created_at=NOW, deleted_at=NOW
        )
        # One experience per participant is enforced, so the deleted one lives
        # in another event.
        other_event = create_event(db, me.user_id, "Outro evento")
        removed = create_experience(db, me.user_id, other_event, deleted_at=NOW)
        add_photo(db, removed, "https://img/deleted-experience.jpg", created_at=NOW)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, headers=headers)

    assert response.status_code == 200
    assert urls(response) == ["https://img/live.jpg"]


def test_photo_item_has_the_documented_shape(photos_client) -> None:
    client, session = photos_client
    created_at = NOW - timedelta(hours=1)
    with session() as db:
        me = create_user(db)
        event = create_event(db, me.user_id, "Pelada no Parcão")
        experience = create_experience(db, me.user_id, event)
        photo = add_photo(db, experience, "https://img/a.jpg", created_at=created_at)
        db.commit()
        headers = make_token(me.user_id)
        photo_id, event_id = str(photo.photo_id), str(event.event_id)

    body = client.get(URL, headers=headers).json()

    [item] = body["items"]
    assert set(item) == {
        "photo_id",
        "photo_url",
        "event",
        "description",
        "created_at",
    }
    assert item["photo_id"] == photo_id
    assert item["photo_url"] == "https://img/a.jpg"
    assert item["event"] == {"id": event_id, "title": "Pelada no Parcão"}
    assert item["description"] == "Foi demais"
    assert datetime.fromisoformat(item["created_at"]).replace(tzinfo=UTC) == created_at
    assert body["next_cursor"] is None


def test_photos_are_ordered_newest_first_regardless_of_id_order(
    photos_client,
) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        event = create_event(db, me.user_id, "Pelada no Parcão")
        experience = create_experience(db, me.user_id, event)
        ids = sorted(uuid4() for _ in range(3))
        for index, photo_id in enumerate(ids):
            add_photo(
                db,
                experience,
                f"https://img/p{index}.jpg",
                created_at=NOW - timedelta(days=3 - index),
                photo_id=photo_id,
            )
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, headers=headers)

    assert urls(response) == [
        "https://img/p2.jpg",
        "https://img/p1.jpg",
        "https://img/p0.jpg",
    ]


def test_pagination_walks_every_photo_once_even_with_equal_dates(
    photos_client,
) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        event = create_event(db, me.user_id, "Pelada no Parcão")
        experience = create_experience(db, me.user_id, event)
        expected: set[str] = set()
        for index in range(7):
            photo = add_photo(
                db,
                experience,
                f"https://img/p{index}.jpg",
                created_at=NOW - timedelta(hours=index // 2),
            )
            expected.add(str(photo.photo_id))
        db.commit()
        headers = make_token(me.user_id)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = client.get(URL, params=params, headers=headers).json()
        seen += [item["photo_id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == 7
    assert set(seen) == expected


def test_exact_page_size_returns_no_next_cursor(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        event = create_event(db, me.user_id, "Pelada no Parcão")
        experience = create_experience(db, me.user_id, event)
        for index in range(2):
            add_photo(
                db,
                experience,
                f"https://img/p{index}.jpg",
                created_at=NOW - timedelta(hours=index),
            )
        db.commit()
        headers = make_token(me.user_id)

    body = client.get(URL, params={"limit": 2}, headers=headers).json()

    assert len(body["items"]) == 2
    assert body["next_cursor"] is None


def test_default_page_size_is_30(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        event = create_event(db, me.user_id, "Pelada no Parcão")
        experience = create_experience(db, me.user_id, event)
        for index in range(31):
            add_photo(
                db,
                experience,
                f"https://img/p{index}.jpg",
                created_at=NOW - timedelta(minutes=index),
            )
        db.commit()
        headers = make_token(me.user_id)

    body = client.get(URL, headers=headers).json()

    assert len(body["items"]) == 30
    assert body["next_cursor"] is not None


def test_empty_cursor_is_treated_as_first_page(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        event = create_event(db, me.user_id, "Pelada no Parcão")
        experience = create_experience(db, me.user_id, event)
        add_photo(db, experience, "https://img/a.jpg", created_at=NOW)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params={"limit": 30, "cursor": ""}, headers=headers)

    assert response.status_code == 200
    assert urls(response) == ["https://img/a.jpg"]


def test_user_without_photos_gets_empty_page(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"limit": "abc"},
        {"cursor": "not-a-valid-cursor"},
    ],
)
def test_invalid_pagination_returns_400(photos_client, params: dict) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(URL, params=params, headers=headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_missing_token_returns_401(photos_client) -> None:
    client, _ = photos_client

    response = client.get(URL)

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_invalid_token_returns_401(photos_client) -> None:
    client, _ = photos_client

    response = client.get(URL, headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


# ---------------------------------------------------------------------------
# GET /users/{user_id}/photos
# ---------------------------------------------------------------------------


def connect(db: Session, requester_id: UUID, receiver_id: UUID) -> None:
    db.add(
        UserConnectionModel(
            requester_id=requester_id,
            receiver_id=receiver_id,
            status=UserConnectionStatusEnum.CONFIRMED,
        )
    )
    db.flush()


def test_connection_sees_only_the_photos_of_public_events(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        owner = create_user(db)
        visitor = create_user(db)
        connect(db, visitor.user_id, owner.user_id)
        public = create_event(db, owner.user_id, "Pelada no Parcão")
        private = create_event(db, owner.user_id, "Aniversário")
        private.event_privacy = EventPrivacyEnum.PRIVATE
        add_photo(
            db,
            create_experience(db, owner.user_id, public),
            "https://img/a.jpg",
            created_at=NOW,
        )
        add_photo(
            db,
            create_experience(db, owner.user_id, private),
            "https://img/b.jpg",
            created_at=NOW,
        )
        db.commit()
        owner_id = owner.user_id
        visitor_headers = make_token(visitor.user_id)
        owner_headers = make_token(owner.user_id)

    url = f"/users/{owner_id}/photos"
    visitor_view = client.get(url, headers=visitor_headers)
    owner_view = client.get(url, headers=owner_headers)

    assert visitor_view.status_code == 200, visitor_view.text
    assert [item["photo_url"] for item in visitor_view.json()["items"]] == [
        "https://img/a.jpg"
    ]
    assert len(owner_view.json()["items"]) == 2
    profile = client.get(f"/users/{owner_id}", headers=visitor_headers).json()
    assert profile["photos_count"] == 1
    assert profile["events_count"] == 1


def test_profile_photos_are_hidden_by_a_block(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        owner = create_user(db)
        visitor = create_user(db)
        db.add(UserBlockModel(blocker_id=owner.user_id, blocked_id=visitor.user_id))
        db.commit()
        owner_id = owner.user_id
        headers = make_token(visitor.user_id)

    response = client.get(f"/users/{owner_id}/photos", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_profile_photos_of_an_unknown_user_return_404(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        me = create_user(db)
        db.commit()
        headers = make_token(me.user_id)

    response = client.get(f"/users/{uuid4()}/photos", headers=headers)

    assert response.status_code == 404


def test_person_gallery_is_only_for_connections(photos_client) -> None:
    client, session = photos_client
    with session() as db:
        owner = create_user(db)
        stranger = create_user(db)
        event = create_event(db, owner.user_id, "Pelada no Parcão")
        add_photo(
            db,
            create_experience(db, owner.user_id, event),
            "https://img/a.jpg",
            created_at=NOW,
        )
        db.commit()
        owner_id = owner.user_id
        headers = make_token(stranger.user_id)

    response = client.get(f"/users/{owner_id}/photos", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Only connections can see photos"}


def test_business_gallery_is_public_with_the_photos_of_its_events(
    photos_client,
) -> None:
    client, session = photos_client
    with session() as db:
        business = create_user(db)
        business.user_type = UserTypeEnum.BUSINESS
        participant = create_user(db)
        stranger = create_user(db)
        event = create_event(db, business.user_id, "Show no bar")
        other_event = create_event(db, participant.user_id, "Outro evento")
        add_photo(
            db,
            create_experience(db, participant.user_id, event),
            "https://img/a.jpg",
            created_at=NOW,
        )
        add_photo(
            db,
            create_experience(db, participant.user_id, other_event),
            "https://img/b.jpg",
            created_at=NOW,
        )
        db.commit()
        business_id = business.user_id
        headers = make_token(stranger.user_id)

    response = client.get(f"/users/{business_id}/photos", headers=headers)

    assert response.status_code == 200, response.text
    assert [item["photo_url"] for item in response.json()["items"]] == [
        "https://img/a.jpg"
    ]
    profile = client.get(f"/users/{business_id}", headers=headers).json()
    assert profile["photos_count"] == 1
