from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    EventPrivacyEnum,
    EventStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventInviteLinkModel,
    EventModel,
    UserModel,
)
from app.main import app


@pytest.fixture
def invite_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


def _create_invite_only_event(
    db: Session,
    status: EventStatusEnum = EventStatusEnum.PUBLISHED,
) -> tuple[UUID, UUID]:
    organizer_id = uuid4()
    event_id = uuid4()
    now = datetime.now(UTC)
    db.add(
        UserModel(
            user_id=organizer_id,
            user_type=UserTypeEnum.PERSONAL,
            role=UserRoleEnum.USER,
            email=f"{organizer_id}@hangy.test",
            password_hash="hash",
            name="Ana",
        )
    )
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=organizer_id,
            event_title="Pelada no Parcao",
            event_description="Fut society entre amigos, leva quem quiser.",
            event_latitude=-30.0277,
            event_longitude=-51.2287,
            location_name="Parcao",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=2),
            event_status=status,
            event_privacy=EventPrivacyEnum.INVITE_ONLY,
            cover_photo_url="https://storage/cover.png",
        )
    )
    db.commit()
    return event_id, organizer_id


def _add_invite_link(
    db: Session,
    event_id: UUID,
    organizer_id: UUID,
    token: str,
    expires_at: datetime,
) -> None:
    db.add(
        EventInviteLinkModel(
            event_id=event_id,
            token=token,
            created_by=organizer_id,
            expires_at=expires_at,
        )
    )
    db.commit()


# "Evento publico devolve link sem token" e "Evento por convite devolve link
# com token" ja sao cobertos em tests/test_event_share.py, pelos testes
# test_a_public_event_returns_direct_share_links e
# test_an_invite_only_event_returns_its_invite_token (endpoint
# GET /events/{event_id}/share). Os testes abaixo cobrem o endpoint novo,
# GET /invites/{token}.


def test_a_valid_token_resolves_to_its_event(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = invite_client
    token = "valid-invite-token"
    with session_factory() as db:
        event_id, organizer_id = _create_invite_only_event(db)
        _add_invite_link(
            db,
            event_id,
            organizer_id,
            token,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )

    response = client.get(f"/invites/{token}")

    assert response.status_code == 200
    assert response.json() == {
        "event_id": str(event_id),
        "title": "Pelada no Parcao",
        "event_date": response.json()["event_date"],
        "location_name": "Parcao",
        "cover_photo_url": "https://storage/cover.png",
        "privacy": "INVITE_ONLY",
        "requires_login": True,
    }


def test_an_expired_token_returns_gone(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = invite_client
    token = "expired-invite-token"
    with session_factory() as db:
        event_id, organizer_id = _create_invite_only_event(db)
        _add_invite_link(
            db,
            event_id,
            organizer_id,
            token,
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )

    response = client.get(f"/invites/{token}")

    assert response.status_code == 410
    assert response.json() == {"detail": "Invite link expired"}


def test_an_unknown_token_returns_not_found(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = invite_client

    response = client.get("/invites/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_invite_preview_does_not_expose_the_event_description(
    invite_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = invite_client
    token = "valid-invite-token"
    with session_factory() as db:
        event_id, organizer_id = _create_invite_only_event(db)
        _add_invite_link(
            db,
            event_id,
            organizer_id,
            token,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )

    response = client.get(f"/invites/{token}")

    assert response.status_code == 200
    body = response.json()
    assert "description" not in body
    assert set(body) == {
        "event_id",
        "title",
        "event_date",
        "location_name",
        "cover_photo_url",
        "privacy",
        "requires_login",
    }
