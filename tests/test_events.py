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
    organizer_id, confirmed_id, pending_id, rejected_id = (
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
            for user_id in (organizer_id, confirmed_id, pending_id, rejected_id)
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
                user_id=rejected_id,
                event_id=event_id,
                status=EventParticipantStatusEnum.REJECTED,
            ),
        ]
    )
    db.commit()
    return event_id, organizer_id, confirmed_id, pending_id, rejected_id


def test_cancel_event_marks_it_cancelled_and_notifies_participants(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, confirmed_id, pending_id, _ = _create_event(db)

    response = client.patch(
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

    response = client.patch(
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

    response = client.patch(
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

    response = client.patch(
        f"/events/{uuid4()}/cancel",
        json={"reason": "Chuva"},
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def _reschedule(
    session_factory: sessionmaker[Session],
    event_id: UUID,
    starts_in: timedelta,
    ends_in: timedelta,
) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        event.starts_at = now + starts_in
        event.ends_at = now + ends_in
        db.commit()
    return now + starts_in, now + ends_in


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def test_finish_closes_a_running_event_and_moves_its_end_to_now(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, _, _, _ = _create_event(db)
    _, original_end = _reschedule(
        session_factory, event_id, timedelta(hours=-1), timedelta(hours=1)
    )

    before = datetime.now(UTC)
    response = client.patch(
        f"/events/{event_id}/finish",
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == str(event_id)
    assert body["status"] == "FINISHED"
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_status is EventStatusEnum.FINISHED
        assert before <= _as_utc(event.ends_at) < original_end
        # Finishing is not cancelling: nobody gets a notification.
        assert db.scalars(select(NotificationModel)).all() == []


def test_finish_keeps_the_original_end_when_it_already_passed(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, _, _, _ = _create_event(db)
    _, original_end = _reschedule(
        session_factory, event_id, timedelta(hours=-3), timedelta(hours=-1)
    )

    response = client.patch(
        f"/events/{event_id}/finish",
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 200
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_status is EventStatusEnum.FINISHED
        assert _as_utc(event.ends_at) == original_end


def test_finishing_twice_returns_the_same_result(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, _, _, _ = _create_event(db)
    _reschedule(session_factory, event_id, timedelta(hours=-1), timedelta(hours=1))
    headers = {"Authorization": f"Bearer {_token_for(organizer_id)}"}

    first = client.patch(f"/events/{event_id}/finish", headers=headers)
    second = client.patch(f"/events/{event_id}/finish", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()


def test_cannot_finish_an_event_before_it_starts(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, _, _, _ = _create_event(db)
    _reschedule(session_factory, event_id, timedelta(minutes=1), timedelta(hours=2))

    response = client.patch(
        f"/events/{event_id}/finish",
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Event has not started yet"}
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_status is EventStatusEnum.PUBLISHED


def test_cannot_finish_a_cancelled_event(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, _, _, _ = _create_event(db, EventStatusEnum.CANCELLED)
    _reschedule(session_factory, event_id, timedelta(hours=-1), timedelta(hours=1))

    response = client.patch(
        f"/events/{event_id}/finish",
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Event is cancelled"}


def test_only_the_organizer_can_finish_an_event(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, _, confirmed_id, _, _ = _create_event(db)
    _reschedule(session_factory, event_id, timedelta(hours=-1), timedelta(hours=1))

    response = client.patch(
        f"/events/{event_id}/finish",
        headers={"Authorization": f"Bearer {_token_for(confirmed_id)}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only the organizer can edit this event"}


def test_finish_returns_not_found_for_an_unknown_event(
    events_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        _, organizer_id, _, _, _ = _create_event(db)

    response = client.patch(
        f"/events/{uuid4()}/finish",
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


@pytest.mark.parametrize(
    ("ends_in", "expected_status"),
    [(timedelta(seconds=-1), "FINISHED"), (timedelta(minutes=5), "PUBLISHED")],
)
def test_event_details_report_finished_once_the_end_passes_without_a_status_change(
    events_client: tuple[TestClient, sessionmaker[Session]],
    ends_in: timedelta,
    expected_status: str,
) -> None:
    client, session_factory = events_client
    with session_factory() as db:
        event_id, organizer_id, _, _, _ = _create_event(db)
    _reschedule(session_factory, event_id, timedelta(hours=-2), ends_in)

    response = client.get(
        f"/events/{event_id}",
        headers={"Authorization": f"Bearer {_token_for(organizer_id)}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_status is EventStatusEnum.PUBLISHED


def test_a_cancelled_event_past_its_end_still_reads_as_cancelled() -> None:
    from app.domain.services.event_timing import effective_event_status

    past = datetime.now(UTC) - timedelta(hours=1)
    assert (
        effective_event_status(EventStatusEnum.CANCELLED, past)
        is EventStatusEnum.CANCELLED
    )
    assert (
        effective_event_status(EventStatusEnum.FINISHED, past)
        is EventStatusEnum.FINISHED
    )
