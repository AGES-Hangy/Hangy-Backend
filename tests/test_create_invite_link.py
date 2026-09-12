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

ORGANIZER_ID = UUID("0c3f0001-0000-4000-8000-000000000001")
OTHER_USER_ID = UUID("0c3f0002-0000-4000-8000-000000000002")
INVITE_ONLY_EVENT_ID = UUID("0c3f0003-0000-4000-8000-000000000003")
PUBLIC_EVENT_ID = UUID("0c3f0004-0000-4000-8000-000000000004")
EVENT_STARTS_AT = datetime.now(UTC) + timedelta(days=7)


@pytest.fixture
def client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as db:
        db.add_all(
            [
                UserModel(
                    user_id=ORGANIZER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="ana@hangy.test",
                    password_hash="hash",
                    name="Ana Souza",
                ),
                UserModel(
                    user_id=OTHER_USER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="bia@hangy.test",
                    password_hash="hash",
                    name="Bia Lima",
                ),
            ]
        )
        db.add_all(
            [
                EventModel(
                    event_id=INVITE_ONLY_EVENT_ID,
                    event_creator_id=ORGANIZER_ID,
                    event_title="Jantar fechado",
                    event_latitude=-30.0277,
                    event_longitude=-51.2287,
                    starts_at=EVENT_STARTS_AT,
                    ends_at=EVENT_STARTS_AT + timedelta(hours=3),
                    event_status=EventStatusEnum.PUBLISHED,
                    event_privacy=EventPrivacyEnum.INVITE_ONLY,
                ),
                EventModel(
                    event_id=PUBLIC_EVENT_ID,
                    event_creator_id=ORGANIZER_ID,
                    event_title="Pelada aberta",
                    event_latitude=-30.0277,
                    event_longitude=-51.2287,
                    starts_at=EVENT_STARTS_AT,
                    ends_at=EVENT_STARTS_AT + timedelta(hours=3),
                    event_status=EventStatusEnum.PUBLISHED,
                    event_privacy=EventPrivacyEnum.PUBLIC,
                ),
            ]
        )
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


def auth_header(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def test_organizer_generates_an_invite_link_for_an_invite_only_event(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.post(
        f"/events/{INVITE_ONLY_EVENT_ID}/invite-link",
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == f"hangy://invite/{body['token']}"
    # The link can never outlive the event it invites people to.
    # SQLite drops the UTC offset on round-trip, unlike Postgres in production.
    expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert expires_at.replace(tzinfo=UTC) == EVENT_STARTS_AT

    with session_factory() as db:
        invite_link = db.get(EventInviteLinkModel, UUID(body["invite_id"]))
        assert invite_link is not None
        assert invite_link.event_id == INVITE_ONLY_EVENT_ID
        assert invite_link.created_by == ORGANIZER_ID
        assert invite_link.token == body["token"]


def test_generating_an_invite_link_requires_authentication(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.post(f"/events/{INVITE_ONLY_EVENT_ID}/invite-link")

    assert response.status_code == 401


def test_a_non_organizer_gets_403(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.post(
        f"/events/{INVITE_ONLY_EVENT_ID}/invite-link",
        headers=auth_header(OTHER_USER_ID),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only the organizer can change privacy"}
    with session_factory() as db:
        assert db.scalars(select(EventInviteLinkModel)).all() == []


def test_an_unknown_event_returns_404(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.post(
        f"/events/{uuid4()}/invite-link",
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_a_non_invite_only_event_returns_409(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.post(
        f"/events/{PUBLIC_EVENT_ID}/invite-link",
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Event is not invite only"}
    with session_factory() as db:
        assert db.scalars(select(EventInviteLinkModel)).all() == []


def test_generated_tokens_are_unique(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    first = test_client.post(
        f"/events/{INVITE_ONLY_EVENT_ID}/invite-link",
        headers=auth_header(ORGANIZER_ID),
    )
    second = test_client.post(
        f"/events/{INVITE_ONLY_EVENT_ID}/invite-link",
        headers=auth_header(ORGANIZER_ID),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["token"] != second.json()["token"]
    assert first.json()["invite_id"] != second.json()["invite_id"]
