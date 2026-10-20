from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import (
    DevicePlatformEnum,
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services.notification_dispatcher import NotificationDispatcher
from app.domain.services.starting_soon import StartingSoonService
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.device import SqlAlchemyUserDeviceRepository
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    NotificationModel,
    UserDeviceModel,
    UserModel,
)
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository
from app.infrastructure.repository.starting_soon import SqlAlchemyStartingSoonRepository
from app.jobs import notify_starting_soon
from app.main import app

ORGANIZER_ID = UUID("0c5a0010-0000-4000-8000-000000000001")
USER_ID = UUID("0c5a0010-0000-4000-8000-000000000002")
OTHER_USER_ID = UUID("0c5a0010-0000-4000-8000-000000000003")

WINDOW_MINUTES = 60


class FakePushSender:
    def __init__(self) -> None:
        self.sent: list[tuple[list[str], str, str, dict[str, str]]] = []

    def send(
        self, tokens: list[str], title: str, body: str, data: dict[str, str]
    ) -> list[str]:
        self.sent.append((tokens, title, body, data))
        return []


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
                _user(ORGANIZER_ID, "organizer"),
                _user(USER_ID, "user"),
                _user(OTHER_USER_ID, "other"),
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


def _user(user_id: UUID, name: str) -> UserModel:
    return UserModel(
        user_id=user_id,
        user_type=UserTypeEnum.PERSONAL,
        role=UserRoleEnum.USER,
        email=f"{name}@starting-soon.test",
        password_hash="hash",
        name=name,
    )


def _add_event(
    db: Session,
    *,
    starts_in: timedelta,
    status: EventStatusEnum = EventStatusEnum.PUBLISHED,
) -> UUID:
    starts_at = datetime.now(UTC) + starts_in
    event = EventModel(
        event_id=uuid4(),
        event_creator_id=ORGANIZER_ID,
        event_title="Starting Soon",
        event_latitude=0.0,
        event_longitude=0.0,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=3),
        max_participants=None,
        event_status=status,
        event_privacy=EventPrivacyEnum.PUBLIC,
    )
    db.add(event)
    db.commit()
    return event.event_id


def _add_participant(
    db: Session,
    event_id: UUID,
    user_id: UUID = USER_ID,
    status: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> UUID:
    participant = EventParticipantModel(
        user_id=user_id, event_id=event_id, status=status
    )
    db.add(participant)
    db.commit()
    return participant.participant_id


def _run_job(
    db: Session,
    push_sender: FakePushSender | None = None,
    now: datetime | None = None,
) -> int:
    service = StartingSoonService(
        repository=SqlAlchemyStartingSoonRepository(db),
        dispatcher=NotificationDispatcher(
            repository=SqlAlchemyNotificationRepository(db),
            device_repository=SqlAlchemyUserDeviceRepository(db),
            push_sender=push_sender,
        ),
        window_minutes=WINDOW_MINUTES,
    )
    return service.notify_participants(now)


def _starting_soon(db: Session, user_id: UUID | None = None) -> list[NotificationModel]:
    stmt = select(NotificationModel).where(
        NotificationModel.type == NotificationTypeEnum.EVENT_STARTING_SOON
    )
    if user_id is not None:
        stmt = stmt.where(NotificationModel.user_id == user_id)
    return list(db.scalars(stmt))


def _headers(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def test_confirmed_participant_in_window_gets_one_notification(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id)

        assert _run_job(db) == 1

        notifications = _starting_soon(db)
        assert len(notifications) == 1
        assert notifications[0].user_id == USER_ID
        assert notifications[0].read is False


def test_second_run_does_not_duplicate(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id)

        assert _run_job(db) == 1
        assert _run_job(db) == 0

        assert len(_starting_soon(db)) == 1


def test_second_run_from_a_new_session_does_not_duplicate(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id)
        _run_job(db)
    with session_factory() as db:
        assert _run_job(db) == 0
        assert len(_starting_soon(db)) == 1


@pytest.mark.parametrize(
    "starts_in",
    [timedelta(minutes=WINDOW_MINUTES + 1), timedelta(minutes=-1)],
    ids=["too-far-away", "already-started"],
)
def test_event_outside_window_is_ignored(
    client: tuple[TestClient, sessionmaker[Session]], starts_in: timedelta
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=starts_in)
        _add_participant(db, event_id)

        assert _run_job(db) == 0
        assert _starting_soon(db) == []


@pytest.mark.parametrize(
    "event_status", [EventStatusEnum.CANCELLED, EventStatusEnum.DRAFT]
)
def test_event_not_published_is_ignored(
    client: tuple[TestClient, sessionmaker[Session]], event_status: EventStatusEnum
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30), status=event_status)
        _add_participant(db, event_id)

        assert _run_job(db) == 0
        assert _starting_soon(db) == []


def test_deleted_event_is_ignored(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id)
        db.get(EventModel, event_id).deleted_at = datetime.now(UTC)
        db.commit()

        assert _run_job(db) == 0


@pytest.mark.parametrize(
    "participant_status",
    [
        EventParticipantStatusEnum.PENDING,
        EventParticipantStatusEnum.REJECTED,
        EventParticipantStatusEnum.CANCELLED,
        EventParticipantStatusEnum.REMOVED,
    ],
)
def test_participant_not_confirmed_is_ignored(
    client: tuple[TestClient, sessionmaker[Session]],
    participant_status: EventParticipantStatusEnum,
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id, status=participant_status)

        assert _run_job(db) == 0
        assert _starting_soon(db) == []


def test_deleted_user_is_ignored(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id)
        db.get(UserModel, USER_ID).deleted_at = datetime.now(UTC)
        db.commit()

        assert _run_job(db) == 0


def test_only_unwarned_participants_are_notified_after_downtime(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=40))
        _add_participant(db, event_id, USER_ID)
        _run_job(db)  # warns USER_ID, then the job is "down"
        _add_participant(db, event_id, OTHER_USER_ID)

        # Back 20 minutes later: the event has not started yet.
        later = datetime.now(UTC) + timedelta(minutes=20)
        assert _run_job(db, now=later) == 1

        assert len(_starting_soon(db, USER_ID)) == 1
        assert len(_starting_soon(db, OTHER_USER_ID)) == 1


def test_event_that_started_during_downtime_is_not_warned(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=10))
        _add_participant(db, event_id)

        later = datetime.now(UTC) + timedelta(minutes=20)
        assert _run_job(db, now=later) == 0


def test_notification_is_sent_as_push_to_the_participant_devices(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    push_sender = FakePushSender()
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        participant_id = _add_participant(db, event_id)
        db.add(
            UserDeviceModel(
                user_id=USER_ID,
                device_token="ExponentPushToken[user]",
                platform=DevicePlatformEnum.ANDROID,
            )
        )
        db.commit()

        _run_job(db, push_sender)

        assert len(push_sender.sent) == 1
        tokens, title, _, data = push_sender.sent[0]
        assert tokens == ["ExponentPushToken[user]"]
        assert title == "Evento começando"
        assert data["type"] == "EVENT_STARTING_SOON"
        assert data["participant_id"] == str(participant_id)
        assert data["event_id"] == str(event_id)


def test_dispatch_failure_for_one_participant_does_not_stop_the_others(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id, USER_ID)
        _add_participant(db, event_id, OTHER_USER_ID)
        repository = SqlAlchemyStartingSoonRepository(db)
        real_dispatcher = NotificationDispatcher(
            repository=SqlAlchemyNotificationRepository(db)
        )
        calls = 0

        class FlakyDispatcher:
            def dispatch(self, *args, **kwargs) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("boom")
                real_dispatcher.dispatch(*args, **kwargs)

        service = StartingSoonService(
            repository=repository,
            dispatcher=FlakyDispatcher(),  # type: ignore[arg-type]
            window_minutes=WINDOW_MINUTES,
        )

        assert service.notify_participants() == 1
        assert len(_starting_soon(db)) == 1
        # The participant that failed is retried by the next run.
        assert _run_job(db) == 1
        assert len(_starting_soon(db)) == 2


def test_notification_appears_in_the_notifications_list(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id)
        _run_job(db)

    response = test_client.get("/notifications", headers=_headers(USER_ID))

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["type"] for item in items] == ["EVENT_STARTING_SOON"]
    assert items[0]["payload"]["event_title"] == "Starting Soon"
    assert (
        test_client.get("/notifications", headers=_headers(ORGANIZER_ID)).json()[
            "items"
        ]
        == []
    )


def test_job_entry_point_is_idempotent(
    client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, session_factory = client
    monkeypatch.setattr(notify_starting_soon, "SessionLocal", session_factory)
    with session_factory() as db:
        event_id = _add_event(db, starts_in=timedelta(minutes=30))
        _add_participant(db, event_id)

    assert notify_starting_soon.main() == 0
    assert notify_starting_soon.main() == 0

    with session_factory() as db:
        count = db.scalar(
            select(func.count())
            .select_from(NotificationModel)
            .where(NotificationModel.type == NotificationTypeEnum.EVENT_STARTING_SOON)
        )
        assert count == 1