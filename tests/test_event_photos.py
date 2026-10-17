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
from app.infrastructure.repository.models import (
    EventExperienceModel,
    EventModel,
    EventParticipantModel,
    ExperienceImagesModel,
    UserBlockModel,
    UserModel,
)
from app.main import app

ORGANIZER_ID = UUID("a2270000-0000-4000-8000-000000000001")
ANA_ID = UUID("a2270000-0000-4000-8000-000000000002")
BRUNO_ID = UUID("a2270000-0000-4000-8000-000000000003")
OUTSIDER_ID = UUID("a2270000-0000-4000-8000-000000000004")
EVENT_ID = UUID("a2270000-0000-4000-8000-000000000005")
NOW = datetime.now(UTC)

SessionFactory = sessionmaker[Session]


@pytest.fixture
def client() -> Iterator[tuple[TestClient, SessionFactory]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        for user_id, name in (
            (ORGANIZER_ID, "Organizador"),
            (ANA_ID, "Ana Souza"),
            (BRUNO_ID, "Bruno Lima"),
            (OUTSIDER_ID, "Terceiro"),
        ):
            db.add(
                UserModel(
                    user_id=user_id,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email=f"{user_id}@hangy.test",
                    password_hash="hash",
                    name=name,
                )
            )
        db.add(_event(EVENT_ID, "Pelada encerrada"))
        db.commit()

    def override_get_db() -> Iterator[Session]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _event(
    event_id: UUID,
    title: str,
    *,
    status: EventStatusEnum = EventStatusEnum.FINISHED,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    deleted_at: datetime | None = None,
) -> EventModel:
    return EventModel(
        event_id=event_id,
        event_creator_id=ORGANIZER_ID,
        event_title=title,
        event_latitude=0.0,
        event_longitude=0.0,
        starts_at=NOW - timedelta(days=2),
        ends_at=NOW - timedelta(days=2) + timedelta(hours=2),
        event_status=status,
        event_privacy=privacy,
        deleted_at=deleted_at,
    )


def _authorization(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": NOW + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _experience(
    db: Session,
    user_id: UUID,
    event_id: UUID = EVENT_ID,
    *,
    deleted_at: datetime | None = None,
) -> EventExperienceModel:
    participant = EventParticipantModel(
        user_id=user_id,
        event_id=event_id,
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


def _photo(
    db: Session,
    experience: EventExperienceModel,
    url: str,
    *,
    created_at: datetime = NOW,
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


def _get(
    test_client: TestClient,
    user_id: UUID = ANA_ID,
    event_id: UUID = EVENT_ID,
    **params: str | int,
):
    return test_client.get(
        f"/events/{event_id}/photos",
        params=params,
        headers=_authorization(user_id),
    )


def _urls(response) -> list[str]:
    return [item["photo_url"] for item in response.json()["items"]]


def test_photo_item_has_the_documented_shape(client) -> None:
    test_client, session = client
    created_at = NOW - timedelta(hours=1)
    with session() as db:
        photo = _photo(
            db,
            _experience(db, ANA_ID),
            "https://bucket.s3.amazonaws.com/a.jpg",
            created_at=created_at,
        )
        db.commit()
        photo_id = str(photo.photo_id)

    response = _get(test_client, BRUNO_ID)

    assert response.status_code == 200
    body = response.json()
    [item] = body["items"]
    assert set(item) == {"photo_id", "photo_url", "author", "can_delete", "created_at"}
    assert item["photo_id"] == photo_id
    # The URL is returned exactly as stored: no signing, no rewriting.
    assert item["photo_url"] == "https://bucket.s3.amazonaws.com/a.jpg"
    assert item["author"] == {"id": str(ANA_ID), "name": "Ana Souza"}
    assert item["can_delete"] is False
    # SQLite returns naive datetimes; the stored instant is the UTC one.
    assert datetime.fromisoformat(item["created_at"]).replace(tzinfo=UTC) == created_at
    assert body["next_cursor"] is None


def test_can_delete_is_true_for_the_author_and_the_organizer_only(client) -> None:
    test_client, session = client
    with session() as db:
        _photo(db, _experience(db, ANA_ID), "https://img/ana.jpg", created_at=NOW)
        _photo(
            db,
            _experience(db, BRUNO_ID),
            "https://img/bruno.jpg",
            created_at=NOW - timedelta(minutes=1),
        )
        db.commit()

    def can_delete(viewer: UUID) -> dict[str, bool]:
        items = _get(test_client, viewer).json()["items"]
        return {item["photo_url"]: item["can_delete"] for item in items}

    assert can_delete(ANA_ID) == {
        "https://img/ana.jpg": True,
        "https://img/bruno.jpg": False,
    }
    assert can_delete(BRUNO_ID) == {
        "https://img/ana.jpg": False,
        "https://img/bruno.jpg": True,
    }
    assert can_delete(ORGANIZER_ID) == {
        "https://img/ana.jpg": True,
        "https://img/bruno.jpg": True,
    }
    assert can_delete(OUTSIDER_ID) == {
        "https://img/ana.jpg": False,
        "https://img/bruno.jpg": False,
    }


def test_non_participant_can_see_photos_of_a_public_event(client) -> None:
    test_client, session = client
    with session() as db:
        _photo(db, _experience(db, ANA_ID), "https://img/ana.jpg")
        db.commit()

    response = _get(test_client, OUTSIDER_ID)

    assert response.status_code == 200
    assert _urls(response) == ["https://img/ana.jpg"]


def test_only_photos_of_this_event_are_listed(client) -> None:
    test_client, session = client
    other_event_id = uuid4()
    with session() as db:
        db.add(_event(other_event_id, "Outro evento"))
        db.flush()
        _photo(db, _experience(db, ANA_ID), "https://img/this.jpg")
        _photo(
            db, _experience(db, ANA_ID, other_event_id), "https://img/other-event.jpg"
        )
        db.commit()

    response = _get(test_client)

    assert _urls(response) == ["https://img/this.jpg"]


def test_deleted_photos_experiences_and_authors_are_left_out(client) -> None:
    test_client, session = client
    with session() as db:
        live = _experience(db, ANA_ID)
        _photo(db, live, "https://img/live.jpg", created_at=NOW)
        _photo(db, live, "https://img/deleted-photo.jpg", deleted_at=NOW)
        _photo(
            db,
            _experience(db, BRUNO_ID, deleted_at=NOW),
            "https://img/deleted-experience.jpg",
        )
        gone = db.get(UserModel, OUTSIDER_ID)
        gone.deleted_at = NOW
        _photo(db, _experience(db, OUTSIDER_ID), "https://img/deleted-author.jpg")
        db.commit()

    response = _get(test_client)

    assert response.status_code == 200
    assert _urls(response) == ["https://img/live.jpg"]


def test_photos_are_ordered_newest_first_regardless_of_id_order(client) -> None:
    test_client, session = client
    with session() as db:
        experience = _experience(db, ANA_ID)
        # Ids ascend while dates also ascend, so ordering by id would reverse it.
        for index, photo_id in enumerate(sorted(uuid4() for _ in range(3))):
            _photo(
                db,
                experience,
                f"https://img/p{index}.jpg",
                created_at=NOW - timedelta(days=3 - index),
                photo_id=photo_id,
            )
        db.commit()

    response = _get(test_client)

    assert _urls(response) == [
        "https://img/p2.jpg",
        "https://img/p1.jpg",
        "https://img/p0.jpg",
    ]


def test_pagination_walks_every_photo_once_even_with_equal_dates(client) -> None:
    test_client, session = client
    with session() as db:
        experience = _experience(db, ANA_ID)
        expected: set[str] = set()
        for index in range(7):
            # Pairs of photos share the exact same timestamp (tiebreak by id).
            photo = _photo(
                db,
                experience,
                f"https://img/p{index}.jpg",
                created_at=NOW - timedelta(hours=index // 2),
            )
            expected.add(str(photo.photo_id))
        db.commit()

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = _get(test_client, **params).json()
        seen += [item["photo_id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == 7
    assert set(seen) == expected


def test_exact_page_size_returns_no_next_cursor(client) -> None:
    test_client, session = client
    with session() as db:
        experience = _experience(db, ANA_ID)
        for index in range(2):
            _photo(
                db,
                experience,
                f"https://img/p{index}.jpg",
                created_at=NOW - timedelta(hours=index),
            )
        db.commit()

    body = _get(test_client, limit=2).json()

    assert len(body["items"]) == 2
    assert body["next_cursor"] is None


def test_default_page_size_is_30(client) -> None:
    test_client, session = client
    with session() as db:
        experience = _experience(db, ANA_ID)
        for index in range(31):
            _photo(
                db,
                experience,
                f"https://img/p{index}.jpg",
                created_at=NOW - timedelta(minutes=index),
            )
        db.commit()

    body = _get(test_client).json()

    assert len(body["items"]) == 30
    assert body["next_cursor"] is not None


def test_empty_cursor_is_treated_as_first_page(client) -> None:
    test_client, session = client
    with session() as db:
        _photo(db, _experience(db, ANA_ID), "https://img/a.jpg")
        db.commit()

    # The task documents the call as `?limit=30&cursor=`.
    response = _get(test_client, limit=30, cursor="")

    assert response.status_code == 200
    assert _urls(response) == ["https://img/a.jpg"]


def test_event_without_photos_returns_empty_page(client) -> None:
    test_client, _ = client

    response = _get(test_client)

    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_unknown_event_returns_404(client) -> None:
    test_client, _ = client

    response = _get(test_client, event_id=uuid4())

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"deleted_at": NOW},
        {"status": EventStatusEnum.CANCELLED},
        {"status": EventStatusEnum.DRAFT},
    ],
)
def test_deleted_cancelled_and_draft_events_return_404(client, overrides) -> None:
    test_client, session = client
    hidden_id = uuid4()
    with session() as db:
        db.add(_event(hidden_id, "Escondido", **overrides))
        db.commit()

    response = _get(test_client, event_id=hidden_id)

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_invite_only_event_is_hidden_from_non_confirmed_users(client) -> None:
    test_client, session = client
    invite_only_id = uuid4()
    with session() as db:
        db.add(
            _event(
                invite_only_id, "Só convidados", privacy=EventPrivacyEnum.INVITE_ONLY
            )
        )
        db.flush()
        _photo(db, _experience(db, ANA_ID, invite_only_id), "https://img/secret.jpg")
        db.commit()

    outsider = _get(test_client, OUTSIDER_ID, invite_only_id)
    participant = _get(test_client, ANA_ID, invite_only_id)
    organizer = _get(test_client, ORGANIZER_ID, invite_only_id)

    assert outsider.status_code == 404
    assert outsider.json() == {"detail": "Event not found"}
    assert _urls(participant) == ["https://img/secret.jpg"]
    assert _urls(organizer) == ["https://img/secret.jpg"]


def test_viewer_blocked_by_the_organizer_gets_404(client) -> None:
    test_client, session = client
    with session() as db:
        _photo(db, _experience(db, ANA_ID), "https://img/a.jpg")
        db.add(UserBlockModel(blocker_id=ORGANIZER_ID, blocked_id=OUTSIDER_ID))
        db.commit()

    blocked = _get(test_client, OUTSIDER_ID)
    other = _get(test_client, BRUNO_ID)

    assert blocked.status_code == 404
    assert blocked.json() == {"detail": "Event not found"}
    assert other.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": -1},
        {"cursor": "not-a-valid-cursor"},
    ],
)
def test_invalid_pagination_returns_400(client, params: dict) -> None:
    test_client, _ = client

    response = _get(test_client, **params)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_missing_token_returns_401(client) -> None:
    test_client, _ = client

    response = test_client.get(f"/events/{EVENT_ID}/photos")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_invalid_token_returns_401(client) -> None:
    test_client, _ = client

    response = test_client.get(
        f"/events/{EVENT_ID}/photos", headers={"Authorization": "Bearer garbage"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}