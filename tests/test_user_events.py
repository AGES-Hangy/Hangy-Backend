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
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    UserModel,
)
from app.main import app

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

    def override_get_db() -> Iterator[Session]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _authorization(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


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
        f"/users/{user_id}/events", headers=_authorization(viewer_id), params=params
    )
    assert response.status_code == 200
    return response.json()


def test_lists_only_public_events_of_another_user(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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
    client: tuple[TestClient, SessionFactory],
    payload: dict[str, Any],
) -> None:
    test_client, session_factory = client
    owner_id = _register(test_client, payload)
    with session_factory() as db:
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Agenda publica")
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=_authorization(viewer_id)
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
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        viewer_id = _add_user(db, "Visitante")
        db.commit()

    response = test_client.get(
        f"/users/{uuid4()}/events", headers=_authorization(viewer_id)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_deleted_user_returns_404(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        owner_id = _add_user(db, "Excluida", deleted_at=BASE_DATE)
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Pelada")
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=_authorization(viewer_id)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_user_who_blocked_the_viewer_returns_404(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Bloqueado")
        other_viewer_id = _add_user(db, "Outro visitante")
        _add_event(db, owner_id, "Pelada")
        _block(db, blocker_id=owner_id, blocked_id=viewer_id)
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=_authorization(viewer_id)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}
    # The block is one-sided: everyone else still sees the profile.
    assert _titles(_list(test_client, owner_id, other_viewer_id)) == ["Pelada"]


def test_events_of_an_organizer_who_blocked_the_viewer_are_hidden(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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


def test_missing_token_returns_401(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, _ = client

    response = test_client.get(f"/users/{uuid4()}/events")

    assert response.status_code == 401


def test_invalid_token_returns_401(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, _ = client

    response = test_client.get(
        f"/users/{uuid4()}/events", headers={"Authorization": "Bearer invalid"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_deleted_viewer_returns_403(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Excluido", deleted_at=BASE_DATE)
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events", headers=_authorization(viewer_id)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Account has been deleted"}


def test_paginates_with_a_stable_cursor(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Primeiro")
        _add_event(db, owner_id, "Segundo", starts_at=BASE_DATE + timedelta(days=1))
        db.commit()

    body = _list(test_client, owner_id, viewer_id, limit=2)

    assert _titles(body) == ["Primeiro", "Segundo"]
    assert body["next_cursor"] is None


def test_malformed_cursor_restarts_from_the_first_page(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        viewer_id = _add_user(db, "Visitante")
        _add_event(db, owner_id, "Pelada")
        db.commit()

    body = _list(test_client, owner_id, viewer_id, cursor="nao-e-um-cursor")

    assert _titles(body) == ["Pelada"]


def test_user_without_events_returns_an_empty_page(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
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
    client: tuple[TestClient, SessionFactory],
    params: dict[str, Any],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        db.commit()

    response = test_client.get(
        f"/users/{owner_id}/events",
        headers=_authorization(owner_id),
        params=params,
    )

    assert response.status_code == 422


def test_accepts_the_maximum_limit(
    client: tuple[TestClient, SessionFactory],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        owner_id = _add_user(db, "Dona")
        db.commit()

    assert _list(test_client, owner_id, owner_id, limit=50) == {
        "items": [],
        "next_cursor": None,
    }
