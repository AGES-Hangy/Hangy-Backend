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
    NotificationTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    NotificationModel,
    UserModel,
)
from app.main import app

ORGANIZER_ID = UUID("0b2f0001-0000-4000-8000-000000000001")
OTHER_USER_ID = UUID("0b2f0001-0000-4000-8000-000000000002")
PARTICIPANT_USER_ID = UUID("0b2f0001-0000-4000-8000-000000000003")
INVITED_USER_ID = UUID("0b2f0001-0000-4000-8000-000000000004")
CONFIRMED_USER_ID = UUID("0b2f0001-0000-4000-8000-000000000005")

EVENT_ID = UUID("0e000001-0000-4000-8000-000000000001")
LIMITED_EVENT_ID = UUID("0e000002-0000-4000-8000-000000000002")

PENDING_PARTICIPANT_ID = UUID("0a000001-0000-4000-8000-000000000001")
INVITED_PARTICIPANT_ID = UUID("0a000002-0000-4000-8000-000000000002")
CONFIRMED_PARTICIPANT_ID = UUID("0a000003-0000-4000-8000-000000000003")


@pytest.fixture
def client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    starts_at = datetime.now(UTC) + timedelta(days=1)
    ends_at = starts_at + timedelta(hours=3)

    with testing_session() as db:
        db.add_all(
            [
                UserModel(
                    user_id=ORGANIZER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="organizer@hangy.test",
                    password_hash="hash",
                    name="Organizer User",
                ),
                UserModel(
                    user_id=OTHER_USER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="other@hangy.test",
                    password_hash="hash",
                    name="Other User",
                ),
                UserModel(
                    user_id=PARTICIPANT_USER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="participant@hangy.test",
                    password_hash="hash",
                    name="Participant User",
                ),
                UserModel(
                    user_id=INVITED_USER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="invited@hangy.test",
                    password_hash="hash",
                    name="Invited User",
                ),
                UserModel(
                    user_id=CONFIRMED_USER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="confirmed@hangy.test",
                    password_hash="hash",
                    name="Confirmed User",
                ),
            ]
        )

        db.add_all(
            [
                EventModel(
                    event_id=EVENT_ID,
                    event_creator_id=ORGANIZER_ID,
                    event_title="Open Event",
                    event_latitude=0.0,
                    event_longitude=0.0,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    max_participants=None,
                    event_status=EventStatusEnum.PUBLISHED,
                    event_privacy=EventPrivacyEnum.PUBLIC,
                ),
                EventModel(
                    event_id=LIMITED_EVENT_ID,
                    event_creator_id=ORGANIZER_ID,
                    event_title="Limited Event",
                    event_latitude=0.0,
                    event_longitude=0.0,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    max_participants=1,
                    event_status=EventStatusEnum.PUBLISHED,
                    event_privacy=EventPrivacyEnum.PRIVATE,
                ),
            ]
        )

        db.add_all(
            [
                EventParticipantModel(
                    participant_id=PENDING_PARTICIPANT_ID,
                    user_id=PARTICIPANT_USER_ID,
                    event_id=EVENT_ID,
                    status=EventParticipantStatusEnum.PENDING,
                ),
                EventParticipantModel(
                    participant_id=INVITED_PARTICIPANT_ID,
                    user_id=INVITED_USER_ID,
                    event_id=EVENT_ID,
                    status=EventParticipantStatusEnum.INVITED,
                ),
                EventParticipantModel(
                    participant_id=CONFIRMED_PARTICIPANT_ID,
                    user_id=CONFIRMED_USER_ID,
                    event_id=EVENT_ID,
                    status=EventParticipantStatusEnum.CONFIRMED,
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


def auth_header(user_id: UUID = ORGANIZER_ID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def test_approve_pending_participant_returns_confirmed_and_creates_notification(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{PENDING_PARTICIPANT_ID}",
        json={"status": "CONFIRMED"},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["participant_id"] == str(PENDING_PARTICIPANT_ID)
    assert body["status"] == "CONFIRMED"
    assert "updated_at" in body

    with session_factory() as db:
        participant = db.get(EventParticipantModel, PENDING_PARTICIPANT_ID)
        assert participant is not None
        assert participant.status == EventParticipantStatusEnum.CONFIRMED

        notification = db.scalar(
            select(NotificationModel).where(
                NotificationModel.user_id == PARTICIPANT_USER_ID,
                NotificationModel.type == NotificationTypeEnum.EVENT_REQUEST_APPROVED,
            )
        )
        assert notification is not None
        assert notification.read is False

        detail = db.scalar(
            select(EventParticipantNotificationModel).where(
                EventParticipantNotificationModel.notification_id
                == notification.notification_id
            )
        )
        assert detail is not None
        assert detail.participant_id == PENDING_PARTICIPANT_ID


def test_approve_invited_participant_returns_confirmed_and_creates_notification(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{INVITED_PARTICIPANT_ID}",
        json={"status": "CONFIRMED"},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CONFIRMED"

    with session_factory() as db:
        participant = db.get(EventParticipantModel, INVITED_PARTICIPANT_ID)
        assert participant is not None
        assert participant.status == EventParticipantStatusEnum.CONFIRMED


def test_reject_pending_participant_returns_rejected_and_creates_notification(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{PENDING_PARTICIPANT_ID}",
        json={"status": "REJECTED"},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["participant_id"] == str(PENDING_PARTICIPANT_ID)
    assert body["status"] == "REJECTED"

    with session_factory() as db:
        participant = db.get(EventParticipantModel, PENDING_PARTICIPANT_ID)
        assert participant is not None
        assert participant.status == EventParticipantStatusEnum.REJECTED

        notification = db.scalar(
            select(NotificationModel).where(
                NotificationModel.user_id == PARTICIPANT_USER_ID,
                NotificationModel.type == NotificationTypeEnum.EVENT_REQUEST_REJECTED,
            )
        )
        assert notification is not None


def test_remove_confirmed_participant_returns_removed_and_creates_notification(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{CONFIRMED_PARTICIPANT_ID}",
        json={"status": "REMOVED"},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["participant_id"] == str(CONFIRMED_PARTICIPANT_ID)
    assert body["status"] == "REMOVED"

    with session_factory() as db:
        participant = db.get(EventParticipantModel, CONFIRMED_PARTICIPANT_ID)
        assert participant is not None
        assert participant.status == EventParticipantStatusEnum.REMOVED

        notification = db.scalar(
            select(NotificationModel).where(
                NotificationModel.user_id == CONFIRMED_USER_ID,
                NotificationModel.type
                == NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED,
            )
        )
        assert notification is not None


def test_approve_above_capacity_returns_409(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client

    user_a = uuid4()
    user_b = uuid4()
    participant_a = uuid4()
    participant_b = uuid4()

    with session_factory() as db:
        db.add_all(
            [
                UserModel(
                    user_id=user_a,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="a@hangy.test",
                    password_hash="h",
                ),
                UserModel(
                    user_id=user_b,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="b@hangy.test",
                    password_hash="h",
                ),
                EventParticipantModel(
                    participant_id=participant_a,
                    user_id=user_a,
                    event_id=LIMITED_EVENT_ID,
                    status=EventParticipantStatusEnum.CONFIRMED,
                ),
                EventParticipantModel(
                    participant_id=participant_b,
                    user_id=user_b,
                    event_id=LIMITED_EVENT_ID,
                    status=EventParticipantStatusEnum.PENDING,
                ),
            ]
        )
        db.commit()

    response = test_client.patch(
        f"/events/{LIMITED_EVENT_ID}/participants/{participant_b}",
        json={"status": "CONFIRMED"},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Event is full"}


def test_event_without_limit_allows_unlimited_approvals(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{PENDING_PARTICIPANT_ID}",
        json={"status": "CONFIRMED"},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CONFIRMED"


@pytest.mark.parametrize(
    ("initial_status", "invalid_status"),
    [
        (EventParticipantStatusEnum.PENDING, "REMOVED"),
        (EventParticipantStatusEnum.PENDING, "PENDING"),
        (EventParticipantStatusEnum.INVITED, "REMOVED"),
        (EventParticipantStatusEnum.INVITED, "INVITED"),
        (EventParticipantStatusEnum.CONFIRMED, "CONFIRMED"),
        (EventParticipantStatusEnum.CONFIRMED, "REJECTED"),
        (EventParticipantStatusEnum.CONFIRMED, "PENDING"),
        (EventParticipantStatusEnum.REJECTED, "CONFIRMED"),
        (EventParticipantStatusEnum.REMOVED, "CONFIRMED"),
    ],
)
def test_invalid_status_transition_returns_400(
    client: tuple[TestClient, sessionmaker[Session]],
    initial_status: EventParticipantStatusEnum,
    invalid_status: str,
) -> None:
    test_client, session_factory = client
    part_id = uuid4()
    u_id = uuid4()

    with session_factory() as db:
        db.add(
            UserModel(
                user_id=u_id,
                user_type=UserTypeEnum.PERSONAL,
                role=UserRoleEnum.USER,
                email=f"{u_id}@hangy.test",
                password_hash="h",
            )
        )
        db.add(
            EventParticipantModel(
                participant_id=part_id,
                user_id=u_id,
                event_id=EVENT_ID,
                status=initial_status,
            )
        )
        db.commit()

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{part_id}",
        json={"status": invalid_status},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid participant status transition"}


def test_non_organizer_returns_403(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{PENDING_PARTICIPANT_ID}",
        json={"status": "CONFIRMED"},
        headers=auth_header(OTHER_USER_ID),
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Only the event organizer can manage participants"
    }


def test_non_existent_event_returns_404(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.patch(
        f"/events/{uuid4()}/participants/{PENDING_PARTICIPANT_ID}",
        json={"status": "CONFIRMED"},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_non_existent_participant_returns_404(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{uuid4()}",
        json={"status": "CONFIRMED"},
        headers=auth_header(ORGANIZER_ID),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Participant not found"}


def test_unauthenticated_request_returns_401(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    response = test_client.patch(
        f"/events/{EVENT_ID}/participants/{PENDING_PARTICIPANT_ID}",
        json={"status": "CONFIRMED"},
    )

    assert response.status_code == 401


def test_openapi_documents_participant_status_update(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = client

    path_item = test_client.get("/openapi.json").json()["paths"][
        "/events/{event_id}/participants/{participant_id}"
    ]["patch"]

    assert set(path_item["responses"]) >= {"200", "400", "401", "403", "404", "409"}
    assert path_item["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UpdateEventParticipantOutput"
    }
