from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
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
from app.infrastructure.repository.models import EventFavoriteModel, UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.event_participant_model import (
    EventParticipantModel,
)
from app.infrastructure.repository.models.user_block_model import UserBlockModel
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
        "privacy",
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


# --- GET /users/{user_id}/events --------------------------------------------

FUTURE = NOW + timedelta(days=10)
PAST = NOW - timedelta(days=10)
DAY = timedelta(days=1)
TERMS_VERSION = "2026-08-01"
EMPTY_TAB = {"items": [], "next_cursor": None}
ALL_TABS = ("history", "created", "interests", "confirmed")

PERSONAL_PAYLOAD = {
    "user_type": "PERSONAL",
    "email": "felipe@hangy.com",
    "password": "strong-password",
    "name": "Felipe Souza",
    "cpf": "52998224725",
    "phone": "51999990000",
    "date_of_birth": "2000-04-12",
    "state": "RS",
    "city": "Porto Alegre",
    "accepted_terms_version": TERMS_VERSION,
}
BUSINESS_PAYLOAD = {
    "user_type": "BUSINESS",
    "email": "contato@bar.com",
    "password": "senha-forte-123",
    "business_name": "Bar do Zé",
    "cnpj": "11222333000181",
    "phone": "5133330000",
    "description": "Bar e petiscaria",
    "location": {"latitude": -30.0331, "longitude": -51.23},
    "address": "Av. Independência, 100 — Porto Alegre",
    "accepted_terms_version": TERMS_VERSION,
}


def _add_user(
    db: Session,
    name: str,
    user_type: UserTypeEnum = UserTypeEnum.PERSONAL,
    deleted_at: datetime | None = None,
) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=user_type,
            role=UserRoleEnum.USER,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
            deleted_at=deleted_at,
        )
    )
    db.flush()
    return user_id


def _add_event(
    db: Session,
    creator_id: UUID,
    title: str,
    starts_at: datetime = FUTURE,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    event_id: UUID | None = None,
    deleted_at: datetime | None = None,
) -> UUID:
    event_id = event_id or uuid4()
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=creator_id,
            event_title=title,
            event_description="Descricao que nao deve aparecer",
            event_latitude=-30.0277,
            event_longitude=-51.2287,
            location_name="Parcão",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=3),
            event_status=status,
            event_privacy=privacy,
            cover_photo_url=f"https://images.hangy.test/{event_id}.png",
            deleted_at=deleted_at,
        )
    )
    db.flush()
    return event_id


def _add_participant(
    db: Session,
    event_id: UUID,
    user_id: UUID,
    status: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> None:
    db.add(EventParticipantModel(event_id=event_id, user_id=user_id, status=status))
    db.flush()


def _favorite(db: Session, event_id: UUID, user_id: UUID) -> None:
    db.add(EventFavoriteModel(event_id=event_id, user_id=user_id))
    db.flush()


def _block(db: Session, blocker_id: UUID, blocked_id: UUID) -> None:
    db.add(UserBlockModel(blocker_id=blocker_id, blocked_id=blocked_id))
    db.flush()


def _register(client: TestClient, payload: dict[str, Any]) -> UUID:
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    return UUID(response.json()["user"]["id"])


def _titles(tab: dict[str, Any]) -> list[str]:
    return [item["title"] for item in tab["items"]]


def _list(
    client: TestClient, user_id: UUID, viewer_id: UUID, **params: Any
) -> dict[str, Any]:
    response = client.get(
        f"/users/{user_id}/events", headers=make_token(viewer_id), params=params
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == set(ALL_TABS)
    return body


def test_personal_owner_sees_every_tab_with_any_privacy(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        _add_event(db, owner_id, "Criado publico", starts_at=FUTURE)
        _add_event(
            db,
            owner_id,
            "Criado privado",
            starts_at=FUTURE + DAY,
            privacy=EventPrivacyEnum.PRIVATE,
        )
        _add_event(
            db,
            owner_id,
            "Criado so convite",
            starts_at=FUTURE + 2 * DAY,
            privacy=EventPrivacyEnum.INVITE_ONLY,
        )
        _add_event(
            db,
            owner_id,
            "Rascunho",
            starts_at=FUTURE + 3 * DAY,
            status=EventStatusEnum.DRAFT,
        )
        _add_event(db, owner_id, "Criado passado", starts_at=PAST)
        attended_id = _add_event(
            db,
            organizer_id,
            "Fui (privado)",
            starts_at=PAST - DAY,
            privacy=EventPrivacyEnum.PRIVATE,
        )
        _add_participant(db, attended_id, owner_id)
        going_id = _add_event(
            db, organizer_id, "Vou (privado)", privacy=EventPrivacyEnum.PRIVATE
        )
        _add_participant(db, going_id, owner_id)
        wanted_id = _add_event(
            db, organizer_id, "Quero ir (privado)", privacy=EventPrivacyEnum.PRIVATE
        )
        _favorite(db, wanted_id, owner_id)
        db.commit()

    body = _list(test_client, owner_id, owner_id)

    assert _titles(body["history"]) == ["Criado passado", "Fui (privado)"]
    assert _titles(body["created"]) == [
        "Criado publico",
        "Criado privado",
        "Criado so convite",
        "Rascunho",
    ]
    assert _titles(body["interests"]) == ["Quero ir (privado)"]
    assert _titles(body["confirmed"]) == ["Vou (privado)"]
    assert [item["privacy"] for item in body["created"]["items"]] == [
        "PUBLIC",
        "PRIVATE",
        "INVITE_ONLY",
        "PUBLIC",
    ]
    assert [item["participation_status"] for item in body["history"]["items"]] == [
        None,
        "CONFIRMED",
    ]
    assert body["confirmed"]["items"][0]["participation_status"] == "CONFIRMED"
    assert body["interests"]["items"][0]["participation_status"] is None
    assert all(tab["next_cursor"] is None for tab in body.values())


def test_business_owner_gets_null_for_the_personal_tabs(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Bar", user_type=UserTypeEnum.BUSINESS)
        organizer_id = _add_user(db, "Organizadora")
        _add_event(db, owner_id, "Agenda privada", privacy=EventPrivacyEnum.PRIVATE)
        # Neither a participation nor a stray favorite opens the personal tabs.
        going_id = _add_event(db, organizer_id, "Vou")
        _add_participant(db, going_id, owner_id)
        _favorite(db, going_id, owner_id)
        db.commit()

    body = _list(test_client, owner_id, owner_id)

    # Allowed and empty is a list; not applicable is null.
    assert body["history"] == EMPTY_TAB
    assert _titles(body["created"]) == ["Agenda privada"]
    assert body["interests"] is None
    assert body["confirmed"] is None


def test_visitor_sees_only_public_history_and_created(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        viewer_id = _add_user(db, "Visitante")
        created_id = _add_event(db, owner_id, "Criado publico")
        _add_event(db, owner_id, "Criado privado", privacy=EventPrivacyEnum.PRIVATE)
        _add_event(
            db, owner_id, "Criado so convite", privacy=EventPrivacyEnum.INVITE_ONLY
        )
        _add_event(db, owner_id, "Rascunho", status=EventStatusEnum.DRAFT)
        _add_event(
            db,
            owner_id,
            "Passado privado",
            starts_at=PAST,
            privacy=EventPrivacyEnum.PRIVATE,
        )
        attended_id = _add_event(db, organizer_id, "Fui", starts_at=PAST)
        _add_participant(db, attended_id, owner_id)
        attended_private_id = _add_event(
            db,
            organizer_id,
            "Fui (privado)",
            starts_at=PAST,
            privacy=EventPrivacyEnum.PRIVATE,
        )
        _add_participant(db, attended_private_id, owner_id)
        # The owner's plans and interests are not the visitor's business.
        going_id = _add_event(db, organizer_id, "Vou")
        _add_participant(db, going_id, owner_id)
        _favorite(db, going_id, owner_id)
        # Nor does the visitor's own participation leak into this profile.
        _add_participant(db, created_id, viewer_id)
        db.commit()

    body = _list(test_client, owner_id, viewer_id)

    assert _titles(body["history"]) == ["Fui"]
    assert _titles(body["created"]) == ["Criado publico"]
    assert body["interests"] is None
    assert body["confirmed"] is None
    assert body["history"]["items"][0]["participation_status"] is None

    item = body["created"]["items"][0]
    assert datetime.fromisoformat(item.pop("event_date")).replace(tzinfo=UTC) == FUTURE
    assert item == {
        "event_id": str(created_id),
        "title": "Criado publico",
        "location_name": "Parcão",
        "cover_photo_url": f"https://images.hangy.test/{created_id}.png",
        "privacy": "PUBLIC",
        "participation_status": None,
    }


@pytest.mark.parametrize(
    "status",
    [
        EventParticipantStatusEnum.PENDING,
        EventParticipantStatusEnum.REJECTED,
        EventParticipantStatusEnum.CANCELLED,
        EventParticipantStatusEnum.REMOVED,
    ],
)
def test_only_confirmed_participations_are_listed(
    events_client: tuple[TestClient, sessionmaker[Session]],
    status: EventParticipantStatusEnum,
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        _add_participant(db, _add_event(db, organizer_id, "Futuro"), owner_id, status)
        _add_participant(
            db,
            _add_event(db, organizer_id, "Passado", starts_at=PAST),
            owner_id,
            status,
        )
        db.commit()

    body = _list(test_client, owner_id, owner_id)

    assert body == dict.fromkeys(ALL_TABS, EMPTY_TAB)


def test_ended_events_move_to_history_newest_first(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        # Still PUBLISHED: nothing flips the status once ends_at goes by.
        elapsed_id = _add_event(db, owner_id, "Criado e encerrado", starts_at=PAST)
        _add_participant(db, elapsed_id, owner_id)
        # Closed early: over even though its date is still ahead.
        _add_event(db, owner_id, "Criado e finalizado", status=EventStatusEnum.FINISHED)
        attended_id = _add_event(db, organizer_id, "Participei", starts_at=PAST - DAY)
        _add_participant(db, attended_id, owner_id)
        favorited_id = _add_event(
            db, organizer_id, "Favorito encerrado", starts_at=PAST - 2 * DAY
        )
        _favorite(db, favorited_id, owner_id)
        _add_event(db, owner_id, "Criado futuro", starts_at=FUTURE + DAY)
        db.commit()

    body = _list(test_client, owner_id, owner_id)

    # Created and attended, yet listed once; a favorite alone is no history.
    assert _titles(body["history"]) == [
        "Criado e finalizado",
        "Criado e encerrado",
        "Participei",
    ]
    assert _titles(body["created"]) == ["Criado futuro"]
    assert body["interests"] == EMPTY_TAB
    assert body["confirmed"] == EMPTY_TAB


@pytest.mark.parametrize("starts_at", [FUTURE, PAST])
def test_cancelled_and_deleted_events_are_never_listed(
    events_client: tuple[TestClient, sessionmaker[Session]],
    starts_at: datetime,
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        hidden = (
            {
                "status": EventStatusEnum.CANCELLED,
                "deleted_at": None,
            },
            {"status": EventStatusEnum.PUBLISHED, "deleted_at": NOW},
        )
        for kwargs in hidden:
            _add_event(db, owner_id, "Criado", starts_at=starts_at, **kwargs)
            event_id = _add_event(
                db, organizer_id, "De outra pessoa", starts_at=starts_at, **kwargs
            )
            _add_participant(db, event_id, owner_id)
            _favorite(db, event_id, owner_id)
        db.commit()

    body = _list(test_client, owner_id, owner_id)

    assert body == dict.fromkeys(ALL_TABS, EMPTY_TAB)


def test_interests_resolve_visibility_on_read_and_keep_the_favorite(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        blocker_id = _add_user(db, "Bloqueou a dona")
        other_id = _add_user(db, "Outro usuario")
        _favorite(db, _add_event(db, organizer_id, "Visivel"), owner_id)
        _favorite(
            db,
            _add_event(
                db,
                organizer_id,
                "Privado visivel",
                starts_at=FUTURE + DAY,
                privacy=EventPrivacyEnum.PRIVATE,
            ),
            owner_id,
        )
        joined_id = _add_event(
            db,
            organizer_id,
            "So convite com presenca",
            starts_at=FUTURE + 2 * DAY,
            privacy=EventPrivacyEnum.INVITE_ONLY,
        )
        _favorite(db, joined_id, owner_id)
        _add_participant(db, joined_id, owner_id)
        # Favorited while public, then closed behind an invite link.
        _favorite(
            db,
            _add_event(
                db,
                organizer_id,
                "Virou so convite",
                privacy=EventPrivacyEnum.INVITE_ONLY,
            ),
            owner_id,
        )
        _favorite(db, _add_event(db, blocker_id, "De quem bloqueou"), owner_id)
        _favorite(
            db,
            _add_event(
                db, organizer_id, "Voltou a rascunho", status=EventStatusEnum.DRAFT
            ),
            owner_id,
        )
        # Someone else's favorite never shows up in this profile.
        _favorite(db, _add_event(db, organizer_id, "Favorito de outro"), other_id)
        _block(db, blocker_id=blocker_id, blocked_id=owner_id)
        db.commit()

    body = _list(test_client, owner_id, owner_id)

    assert _titles(body["interests"]) == [
        "Visivel",
        "Privado visivel",
        "So convite com presenca",
    ]
    with session_factory() as db:
        stored = db.query(EventFavoriteModel).filter_by(user_id=owner_id).count()
    assert stored == 6


def _add_events_for_tab(
    db: Session, tab: str, owner_id: UUID, organizer_id: UUID
) -> list[str]:
    """Five events of one tab, two of them tied on the date; returns the order."""
    base = PAST if tab == "history" else FUTURE
    creator_id = owner_id if tab in ("history", "created") else organizer_id
    # Ids sort opposite to both insertion and title order.
    specs = [
        ("E", base, UUID(int=1)),
        ("D", base, UUID(int=2)),
        ("C", base - DAY, UUID(int=3)),
        ("B", base + DAY, UUID(int=4)),
        ("A", base + 2 * DAY, UUID(int=5)),
    ]
    for title, starts_at, event_id in specs:
        _add_event(db, creator_id, title, starts_at=starts_at, event_id=event_id)
        if tab == "confirmed":
            _add_participant(db, event_id, owner_id)
        if tab == "interests":
            _favorite(db, event_id, owner_id)
    ordered = sorted(
        specs, key=lambda spec: (spec[1], spec[2]), reverse=tab == "history"
    )
    return [title for title, _, _ in ordered]


@pytest.mark.parametrize("tab", ALL_TABS)
def test_paginates_one_tab_without_repeating_or_skipping(
    events_client: tuple[TestClient, sessionmaker[Session]],
    tab: str,
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        expected = _add_events_for_tab(db, tab, owner_id, organizer_id)
        db.commit()

    first = _list(test_client, owner_id, owner_id, limit=2)
    walked = _titles(first[tab])
    cursor = first[tab]["next_cursor"]
    assert cursor is not None
    while cursor is not None:
        page = _list(test_client, owner_id, owner_id, limit=2, tab=tab, cursor=cursor)
        # Continuing one tab leaves the others out, even the allowed ones.
        assert [name for name in ALL_TABS if page[name] is not None] == [tab]
        assert len(page[tab]["items"]) <= 2
        walked += _titles(page[tab])
        cursor = page[tab]["next_cursor"]

    assert walked == expected


def test_exact_page_size_has_no_next_cursor(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        _add_event(db, owner_id, "Primeiro")
        _add_event(db, owner_id, "Segundo", starts_at=FUTURE + DAY)
        db.commit()

    body = _list(test_client, owner_id, owner_id, limit=2)

    assert _titles(body["created"]) == ["Primeiro", "Segundo"]
    assert body["created"]["next_cursor"] is None


def _valid_cursor(client: TestClient, owner_id: UUID, viewer_id: UUID) -> str:
    cursor = _list(client, owner_id, viewer_id, limit=1)["created"]["next_cursor"]
    assert cursor is not None
    return cursor


@pytest.mark.parametrize(
    ("viewer", "user_type", "tab"),
    [
        ("owner", UserTypeEnum.PERSONAL, "photos"),
        ("owner", UserTypeEnum.PERSONAL, "CREATED"),
        # `past` only exists on GET /users/me/events.
        ("owner", UserTypeEnum.PERSONAL, "past"),
        ("owner", UserTypeEnum.BUSINESS, "interests"),
        ("owner", UserTypeEnum.BUSINESS, "confirmed"),
        ("visitor", UserTypeEnum.PERSONAL, "interests"),
        ("visitor", UserTypeEnum.PERSONAL, "confirmed"),
    ],
)
def test_unknown_or_not_allowed_tab_returns_400(
    events_client: tuple[TestClient, sessionmaker[Session]],
    viewer: str,
    user_type: UserTypeEnum,
    tab: str,
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona", user_type=user_type)
        visitor_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Primeiro")
        _add_event(db, owner_id, "Segundo", starts_at=FUTURE + DAY)
        db.commit()
    viewer_id = owner_id if viewer == "owner" else visitor_id
    cursor = _valid_cursor(test_client, owner_id, viewer_id)

    response = test_client.get(
        f"/users/{owner_id}/events",
        headers=make_token(viewer_id),
        params={"tab": tab, "cursor": cursor},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid tab"}


def test_tab_and_cursor_only_work_together(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        _add_event(db, owner_id, "Primeiro")
        _add_event(db, owner_id, "Segundo", starts_at=FUTURE + DAY)
        db.commit()
    cursor = _valid_cursor(test_client, owner_id, owner_id)

    for params in ({"cursor": cursor}, {"tab": "created"}):
        response = test_client.get(
            f"/users/{owner_id}/events", headers=make_token(owner_id), params=params
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid tab"}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"tab": "created", "cursor": "nao-e-um-cursor"},
    ],
)
def test_invalid_pagination_on_profile_events_returns_400(
    events_client: tuple[TestClient, sessionmaker[Session]],
    params: dict[str, Any],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=make_token(owner_id), params=params
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_accepts_the_maximum_limit(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        db.commit()

    body = _list(test_client, owner_id, owner_id, limit=100)

    assert body == dict.fromkeys(ALL_TABS, EMPTY_TAB)


@pytest.mark.parametrize("payload", [PERSONAL_PAYLOAD, BUSINESS_PAYLOAD])
@pytest.mark.parametrize("viewer", ["owner", "visitor"])
def test_profile_events_never_expose_private_data(
    events_client: tuple[TestClient, sessionmaker[Session]],
    payload: dict[str, Any],
    viewer: str,
) -> None:
    test_client, session_factory = events_client
    owner_id = _register(test_client, payload)
    with session_factory() as db:
        visitor_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Agenda publica")
        _add_event(db, owner_id, "Ja aconteceu", starts_at=PAST)
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events",
        headers=make_token(owner_id if viewer == "owner" else visitor_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert _titles(body["created"]) == ["Agenda publica"]
    assert _titles(body["history"]) == ["Ja aconteceu"]
    assert set(body["created"]["items"][0]) == {
        "event_id",
        "title",
        "event_date",
        "location_name",
        "cover_photo_url",
        "privacy",
        "participation_status",
    }
    for sensitive in (
        payload["email"],
        payload["phone"],
        payload.get("cpf"),
        payload.get("cnpj"),
        str(owner_id),
    ):
        if sensitive is not None:
            assert sensitive not in response.text


def test_unknown_user_returns_404(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        viewer_id = _add_user(db, "Visitante")
        db.commit()

    response = test_client.get(
        f"/users/{uuid4()}/events", headers=make_token(viewer_id)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_deleted_user_returns_404(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Excluida", deleted_at=NOW)
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Pelada")
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=make_token(viewer_id)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_user_who_blocked_the_viewer_returns_404(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Bloqueado")
        other_viewer_id = _add_user(db, "Outro visitante")
        _add_event(db, owner_id, "Pelada")
        _block(db, blocker_id=owner_id, blocked_id=viewer_id)
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=make_token(viewer_id)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}
    # Only the pair is affected: everyone else still sees the profile.
    body = _list(test_client, owner_id, other_viewer_id)
    assert _titles(body["created"]) == ["Pelada"]


def test_user_blocked_by_the_viewer_returns_404(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Bloqueou a dona")
        _add_event(db, owner_id, "Pelada")
        _block(db, blocker_id=viewer_id, blocked_id=owner_id)
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=make_token(viewer_id)
    )

    # Same as GET /users/{user_id}: the block hides both sides.
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


@pytest.mark.parametrize("viewer_is_the_blocker", [False, True])
def test_events_of_an_organizer_blocked_either_way_are_hidden(
    events_client: tuple[TestClient, sessionmaker[Session]],
    viewer_is_the_blocker: bool,
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        viewer_id = _add_user(db, "Bloqueado")
        hidden_id = _add_event(
            db, organizer_id, "Do organizador que bloqueou", starts_at=PAST
        )
        _add_participant(db, hidden_id, owner_id)
        _add_event(db, owner_id, "Da dona", starts_at=PAST - DAY)
        if viewer_is_the_blocker:
            _block(db, blocker_id=viewer_id, blocked_id=organizer_id)
        else:
            _block(db, blocker_id=organizer_id, blocked_id=viewer_id)
        db.commit()

    assert _titles(_list(test_client, owner_id, viewer_id)["history"]) == ["Da dona"]
    assert _titles(_list(test_client, owner_id, owner_id)["history"]) == [
        "Do organizador que bloqueou",
        "Da dona",
    ]


def test_profile_events_missing_token_returns_401(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = events_client

    response = test_client.get(f"/users/{uuid4()}/events")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_profile_events_invalid_token_returns_401(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = events_client

    response = test_client.get(
        f"/users/{uuid4()}/events", headers={"Authorization": "Bearer invalid"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_deleted_viewer_returns_403(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Excluido", deleted_at=NOW)
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=make_token(viewer_id)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Account has been deleted"}


# --- GET /users/me/events follows the same tab rules -------------------------


@pytest.mark.parametrize("tab", ["past", "history"])
def test_current_user_past_tab_is_the_history_tab(
    events_client: tuple[TestClient, sessionmaker[Session]],
    tab: str,
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        _add_event(db, owner_id, "Criado e encerrado", starts_at=PAST)
        attended_id = _add_event(db, organizer_id, "Participei", starts_at=PAST - DAY)
        _add_participant(db, attended_id, owner_id)
        db.commit()

    response = test_client.get(URL, params={"tab": tab}, headers=make_token(owner_id))

    assert response.status_code == 200
    body = response.json()
    assert _titles(body) == ["Criado e encerrado", "Participei"]
    assert [item["participation_status"] for item in body["items"]] == [
        None,
        "CONFIRMED",
    ]


@pytest.mark.parametrize("tab", ["created", "interests"])
def test_current_user_events_keep_their_own_tabs(
    events_client: tuple[TestClient, sessionmaker[Session]],
    tab: str,
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        db.commit()

    response = test_client.get(URL, params={"tab": tab}, headers=make_token(owner_id))

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid tab"}
