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
    EventCancelledNotificationModel,
    EventModel,
    EventParticipantModel,
    NotificationModel,
    UserModel,
)
from app.main import app


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


def _token_for(user_id: UUID) -> str:
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _create_event(
    db: Session,
    event_status: EventStatusEnum = EventStatusEnum.PUBLISHED,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    organizer_id, confirmed_id, pending_id, invited_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    event_id = uuid4()
    now = datetime.now(UTC)
    db.add_all(
        [
            UserModel(
                user_id=user_id,
                user_type=UserTypeEnum.PERSONAL,
                role=UserRoleEnum.USER,
                email=f"{user_id}@hangy.test",
                password_hash="hash",
            )
            for user_id in (organizer_id, confirmed_id, pending_id, invited_id)
        ]
    )
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=organizer_id,
            event_title="Piquenique",
            event_latitude=0,
            event_longitude=0,
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=2),
            event_status=event_status,
            event_privacy=EventPrivacyEnum.PUBLIC,
            created_at=now,
            updated_at=now,
        )
    )
    db.add_all(
        [
            EventParticipantModel(
                user_id=confirmed_id,
                event_id=event_id,
                status=EventParticipantStatusEnum.CONFIRMED,
            ),
            EventParticipantModel(
                user_id=pending_id,
                event_id=event_id,
                status=EventParticipantStatusEnum.PENDING,
            ),
            EventParticipantModel(
                user_id=invited_id,
                event_id=event_id,
                status=EventParticipantStatusEnum.INVITED,
            ),
        ]
    )
    db.commit()
    return event_id, organizer_id, confirmed_id, pending_id, invited_id


def test_cancel_event_marks_it_cancelled_and_notifies_participants(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, confirmed_id, pending_id, _ = _create_event(db)

    response = client.post(
        f"/events/{event_id}/cancel",
        json={"reason": "Chuva"},
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 200
    assert response.json()["event_id"] == str(event_id)
    assert response.json()["status"] == "CANCELLED"
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_status is EventStatusEnum.CANCELLED
        notifications = db.scalars(select(NotificationModel)).all()
        assert {notification.user_id for notification in notifications} == {
            confirmed_id,
            pending_id,
        }
        assert all(
            notification.type is NotificationTypeEnum.EVENT_CANCELLED
            for notification in notifications
        )
        details = db.scalars(select(EventCancelledNotificationModel)).all()
        assert {detail.event_id for detail in details} == {event_id}


def test_only_the_organizer_can_cancel_an_event(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, _, confirmed_id, _, _ = _create_event(db)

    response = client.post(
        f"/events/{event_id}/cancel",
        json={"reason": "Chuva"},
        headers={"Authorization": f"Bearer {_token_for(confirmed_id)}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only the organizer can edit this event"}


def test_cannot_cancel_a_finished_event(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, _, _, _ = _create_event(db, EventStatusEnum.FINISHED)

    response = client.post(
        f"/events/{event_id}/cancel",
        json={"reason": "Chuva"},
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Event already finished"}


def test_cancel_returns_not_found_for_an_unknown_event(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        _, organizer_id, _, _, _ = _create_event(db)

    response = client.post(
        f"/events/{uuid4()}/cancel",
        json={"reason": "Chuva"},
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}
