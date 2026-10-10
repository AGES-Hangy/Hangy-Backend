from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine
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


# --- GET /users/{user_id}/events --------------------------------------------

BASE_DATE = datetime(2026, 9, 2, 19, 0, tzinfo=UTC)
TERMS_VERSION = "2026-08-01"

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
    starts_at: datetime = BASE_DATE,
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


def _block(db: Session, blocker_id: UUID, blocked_id: UUID) -> None:
    """Stand-in for task 087's table, which this task must not create."""
    user_block = Table(
        "user_block",
        MetaData(),
        Column("blocker_id", Uuid, nullable=False),
        Column("blocked_id", Uuid, nullable=False),
    )
    user_block.create(db.get_bind(), checkfirst=True)
    db.execute(user_block.insert().values(blocker_id=blocker_id, blocked_id=blocked_id))


def _register(client: TestClient, payload: dict[str, Any]) -> UUID:
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201
    return UUID(response.json()["user"]["id"])


def _titles(response_body: dict[str, Any]) -> list[str]:
    return [item["title"] for item in response_body["items"]]


def _list(
    client: TestClient, user_id: UUID, viewer_id: UUID, **params: Any
) -> dict[str, Any]:
    response = client.get(
        f"/users/{user_id}/events", headers=make_token(viewer_id), params=params
    )
    assert response.status_code == 200
    return response.json()


def test_lists_only_public_events_of_another_user(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Visitante")
        public_id = _add_event(db, owner_id, "Pelada no Parcão")
        _add_event(db, owner_id, "Aniversario", privacy=EventPrivacyEnum.PRIVATE)
        _add_event(db, owner_id, "Racha", privacy=EventPrivacyEnum.INVITE_ONLY)
        db.commit()

    body = _list(test_client, owner_id, viewer_id)

    assert body["next_cursor"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert (
        datetime.fromisoformat(item.pop("event_date")).replace(tzinfo=UTC) == BASE_DATE
    )
    assert item == {
        "event_id": str(public_id),
        "title": "Pelada no Parcão",
        "location_name": "Parcão",
        "cover_photo_url": f"https://images.hangy.test/{public_id}.png",
        "privacy": "PUBLIC",
    }


def test_lists_published_and_finished_events_including_past_ones(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Visitante")
        # Past, but still PUBLISHED: nothing flips the status once it is over.
        _add_event(db, owner_id, "Passado", starts_at=BASE_DATE - timedelta(days=60))
        _add_event(
            db,
            owner_id,
            "Encerrado",
            starts_at=BASE_DATE - timedelta(days=30),
            status=EventStatusEnum.FINISHED,
        )
        _add_event(db, owner_id, "Futuro")
        _add_event(db, owner_id, "Rascunho", status=EventStatusEnum.DRAFT)
        _add_event(db, owner_id, "Cancelado", status=EventStatusEnum.CANCELLED)
        db.commit()

    body = _list(test_client, owner_id, viewer_id)

    assert _titles(body) == ["Passado", "Encerrado", "Futuro"]


def test_lists_public_events_the_user_confirmed_presence_in(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        viewer_id = _add_user(db, "Visitante")
        statuses = {
            "Confirmado": EventParticipantStatusEnum.CONFIRMED,
            "Pendente": EventParticipantStatusEnum.PENDING,
            "Recusado": EventParticipantStatusEnum.REJECTED,
            "Desistiu": EventParticipantStatusEnum.CANCELLED,
            "Removido": EventParticipantStatusEnum.REMOVED,
        }
        for offset, (title, status) in enumerate(statuses.items()):
            event_id = _add_event(
                db, organizer_id, title, starts_at=BASE_DATE + timedelta(days=offset)
            )
            _add_participant(db, event_id, owner_id, status)
        private_id = _add_event(
            db, organizer_id, "Privado confirmado", privacy=EventPrivacyEnum.PRIVATE
        )
        _add_participant(db, private_id, owner_id)
        # Someone else's participation must not leak into the owner's list.
        unrelated_id = _add_event(db, organizer_id, "De outra pessoa")
        _add_participant(db, unrelated_id, viewer_id)
        db.commit()

    body = _list(test_client, owner_id, viewer_id)

    assert _titles(body) == ["Confirmado"]


def test_owner_sees_every_own_event(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        day = timedelta(days=1)
        _add_event(db, owner_id, "Publico", starts_at=BASE_DATE)
        _add_event(
            db,
            owner_id,
            "Privado",
            starts_at=BASE_DATE + day,
            privacy=EventPrivacyEnum.PRIVATE,
        )
        _add_event(
            db,
            owner_id,
            "So convite",
            starts_at=BASE_DATE + 2 * day,
            privacy=EventPrivacyEnum.INVITE_ONLY,
        )
        _add_event(
            db,
            owner_id,
            "Rascunho",
            starts_at=BASE_DATE + 3 * day,
            status=EventStatusEnum.DRAFT,
        )
        _add_event(
            db,
            owner_id,
            "Cancelado",
            starts_at=BASE_DATE + 4 * day,
            status=EventStatusEnum.CANCELLED,
        )
        participated_id = _add_event(
            db,
            organizer_id,
            "Privado de outra pessoa",
            starts_at=BASE_DATE + 5 * day,
            privacy=EventPrivacyEnum.PRIVATE,
        )
        _add_participant(db, participated_id, owner_id)
        _add_event(
            db,
            owner_id,
            "Excluido",
            starts_at=BASE_DATE + 6 * day,
            deleted_at=BASE_DATE,
        )
        db.commit()

    body = _list(test_client, owner_id, owner_id)

    assert _titles(body) == [
        "Publico",
        "Privado",
        "So convite",
        "Rascunho",
        "Cancelado",
        "Privado de outra pessoa",
    ]
    assert body["items"][1]["privacy"] == "PRIVATE"


def test_soft_deleted_events_are_never_listed(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Criado e excluido", deleted_at=BASE_DATE)
        participated_id = _add_event(
            db, organizer_id, "Participado e excluido", deleted_at=BASE_DATE
        )
        _add_participant(db, participated_id, owner_id)
        db.commit()

    assert _list(test_client, owner_id, viewer_id) == {
        "items": [],
        "next_cursor": None,
    }


def test_event_created_and_attended_by_the_user_is_listed_once(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Visitante")
        event_id = _add_event(db, owner_id, "Pelada")
        _add_participant(db, event_id, owner_id)
        db.commit()

    body = _list(test_client, owner_id, viewer_id)

    assert _titles(body) == ["Pelada"]


@pytest.mark.parametrize("payload", [PERSONAL_PAYLOAD, BUSINESS_PAYLOAD])
def test_lists_events_of_personal_and_business_profiles_without_private_data(
    events_client: tuple[TestClient, sessionmaker[Session]],
    payload: dict[str, Any],
) -> None:
    test_client, session_factory = events_client
    owner_id = _register(test_client, payload)
    with session_factory() as db:
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Agenda publica")
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=make_token(viewer_id)
    )

    assert response.status_code == 200
    body = response.json()
    assert _titles(body) == ["Agenda publica"]
    assert set(body["items"][0]) == {
        "event_id",
        "title",
        "event_date",
        "location_name",
        "cover_photo_url",
        "privacy",
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
        owner_id = _add_user(db, "Excluida", deleted_at=BASE_DATE)
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
    # The block is one-sided: everyone else still sees the profile.
    assert _titles(_list(test_client, owner_id, other_viewer_id)) == ["Pelada"]


def test_events_of_an_organizer_who_blocked_the_viewer_are_hidden(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        organizer_id = _add_user(db, "Organizadora")
        viewer_id = _add_user(db, "Bloqueado")
        hidden_id = _add_event(db, organizer_id, "Do organizador que bloqueou")
        _add_participant(db, hidden_id, owner_id)
        _add_event(db, owner_id, "Da dona", starts_at=BASE_DATE + timedelta(days=1))
        _block(db, blocker_id=organizer_id, blocked_id=viewer_id)
        db.commit()

    assert _titles(_list(test_client, owner_id, viewer_id)) == ["Da dona"]
    assert _titles(_list(test_client, owner_id, owner_id)) == [
        "Do organizador que bloqueou",
        "Da dona",
    ]


def test_other_user_events_missing_token_returns_401(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = events_client

    response = test_client.get(f"/users/{uuid4()}/events")

    assert response.status_code == 401


def test_other_user_events_invalid_token_returns_401(
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
        viewer_id = _add_user(db, "Excluido", deleted_at=BASE_DATE)
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=make_token(viewer_id)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Account has been deleted"}


def test_paginates_with_a_stable_cursor(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Visitante")
        # Same date for B and A: the tie is broken by event_id, which sorts
        # opposite to both insertion and title order.
        _add_event(
            db,
            owner_id,
            "B mesmo horario",
            event_id=UUID("00000000-0000-0000-0000-000000000001"),
        )
        _add_event(
            db,
            owner_id,
            "A mesmo horario",
            event_id=UUID("00000000-0000-0000-0000-000000000002"),
        )
        _add_event(db, owner_id, "Anterior", starts_at=BASE_DATE - timedelta(days=1))
        _add_event(db, owner_id, "Seguinte", starts_at=BASE_DATE + timedelta(days=1))
        _add_event(db, owner_id, "Ultimo", starts_at=BASE_DATE + timedelta(days=2))
        db.commit()

    first = _list(test_client, owner_id, viewer_id, limit=2)
    second = _list(
        test_client, owner_id, viewer_id, limit=2, cursor=first["next_cursor"]
    )
    third = _list(
        test_client, owner_id, viewer_id, limit=2, cursor=second["next_cursor"]
    )

    assert _titles(first) == ["Anterior", "B mesmo horario"]
    assert first["next_cursor"] is not None
    assert _titles(second) == ["A mesmo horario", "Seguinte"]
    assert second["next_cursor"] is not None
    assert _titles(third) == ["Ultimo"]
    assert third["next_cursor"] is None


def test_last_full_page_has_no_next_cursor(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Primeiro")
        _add_event(db, owner_id, "Segundo", starts_at=BASE_DATE + timedelta(days=1))
        db.commit()

    body = _list(test_client, owner_id, viewer_id, limit=2)

    assert _titles(body) == ["Primeiro", "Segundo"]
    assert body["next_cursor"] is None


def test_malformed_cursor_returns_400(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Pelada")
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events",
        headers=make_token(viewer_id),
        params={"cursor": "nao-e-um-cursor"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


def test_user_without_events_returns_an_empty_page(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Sem eventos", user_type=UserTypeEnum.BUSINESS)
        viewer_id = _add_user(db, "Visitante")
        db.commit()

    assert _list(test_client, owner_id, viewer_id) == {
        "items": [],
        "next_cursor": None,
    }


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 51}, {"cursor": "x" * 201}],
)
def test_rejects_out_of_bounds_pagination(
    events_client: tuple[TestClient, sessionmaker[Session]],
    params: dict[str, Any],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events",
        headers=make_token(owner_id),
        params=params,
    )

    assert response.status_code == 422


def test_accepts_the_maximum_limit(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = events_client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        db.commit()

    assert _list(test_client, owner_id, owner_id, limit=50) == {
        "items": [],
        "next_cursor": None,
    }
