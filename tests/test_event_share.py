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
def share_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


def _authorization(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _create_event(
    db: Session,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
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
            event_latitude=-30.0277,
            event_longitude=-51.2287,
            location_name="Parcao",
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=2),
            event_status=status,
            event_privacy=privacy,
            cover_photo_url="https://storage/cover.png",
        )
    )
    db.commit()
    return event_id, organizer_id


def test_a_public_event_returns_direct_share_links(
    share_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = share_client
    with session_factory() as db:
        event_id, organizer_id = _create_event(db)

    response = client.get(
        f"/events/{event_id}/share",
        headers=_authorization(organizer_id),
    )

    assert response.status_code == 200
    assert response.json() == {
        "url": f"hangy://event/{event_id}",
        "web_url": f"https://hangy.app/e/{event_id}",
        "title": "Pelada no Parcao",
        "event_date": response.json()["event_date"],
        "location_name": "Parcao",
        "cover_photo_url": "https://storage/cover.png",
    }


def test_an_invite_only_event_returns_its_invite_token(
    share_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = share_client
    token = "valid-invite-token"
    with session_factory() as db:
        event_id, organizer_id = _create_event(db, EventPrivacyEnum.INVITE_ONLY)
        db.add(
            EventInviteLinkModel(
                event_id=event_id,
                token=token,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        db.commit()

    response = client.get(
        f"/events/{event_id}/share",
        headers=_authorization(organizer_id),
    )

    assert response.status_code == 200
    assert response.json()["url"] == f"hangy://invite/{token}"
    assert response.json()["web_url"] == f"https://hangy.app/invite/{token}"


def test_an_expired_invite_link_returns_gone(
    share_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = share_client
    with session_factory() as db:
        event_id, organizer_id = _create_event(db, EventPrivacyEnum.INVITE_ONLY)
        db.add(
            EventInviteLinkModel(
                event_id=event_id,
                token="expired-invite-token",
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
        db.commit()

    response = client.get(
        f"/events/{event_id}/share",
        headers=_authorization(organizer_id),
    )

    assert response.status_code == 410
    assert response.json() == {"detail": "Invite link expired"}


def test_private_event_hides_schedule_and_location_from_preview(
    share_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = share_client
    with session_factory() as db:
        event_id, organizer_id = _create_event(db, EventPrivacyEnum.PRIVATE)

    response = client.get(
        f"/events/{event_id}/share",
        headers=_authorization(organizer_id),
    )

    assert response.status_code == 200
    assert response.json()["event_date"] is None
    assert response.json()["location_name"] is None


def test_cancelled_or_unknown_events_cannot_be_shared(
    share_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = share_client
    with session_factory() as db:
        event_id, organizer_id = _create_event(db, status=EventStatusEnum.CANCELLED)

    for target_event_id in (event_id, uuid4()):
        response = client.get(
            f"/events/{target_event_id}/share",
            headers=_authorization(organizer_id),
        )
        assert response.status_code == 404
        assert response.json() == {"detail": "Event not found"}


def test_event_share_requires_authentication(
    share_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = share_client
    with session_factory() as db:
        event_id, _ = _create_event(db)

    response = client.get(f"/events/{event_id}/share")

    assert response.status_code == 401


def test_openapi_documents_event_share(
    share_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = share_client

    operation = client.get("/openapi.json").json()["paths"]["/events/{event_id}/share"][
        "get"
    ]

    assert set(operation["responses"]) >= {"200", "401", "404", "410", "422"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/EventShareOutput"
    }
