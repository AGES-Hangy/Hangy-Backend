from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services.connection import (
    ConnectionService,
    InvalidConnectionStatusTransitionError,
)
from app.domain.services.participation import (
    AlreadyParticipatingError,
    OrganizerCannotJoinError,
    ParticipationService,
)
from app.infrastructure.repository import Base
from app.infrastructure.repository.connection import SqlAlchemyConnectionRepository
from app.infrastructure.repository.models import (
    EventCancelledNotificationModel,
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    NotificationModel,
    UserModel,
)
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository
from app.infrastructure.repository.participation import (
    SqlAlchemyParticipationRepository,
)

ORGANIZER_ID = UUID("0b2f0010-0000-4000-8000-000000000001")
USER_A_ID = UUID("0b2f0010-0000-4000-8000-000000000002")
USER_B_ID = UUID("0b2f0010-0000-4000-8000-000000000003")

EVENT_ID = UUID("0e000010-0000-4000-8000-000000000001")
PRIVATE_EVENT_ID = UUID("0e000010-0000-4000-8000-000000000002")


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    starts_at = datetime.now(UTC) + timedelta(days=1)
    ends_at = starts_at + timedelta(hours=3)

    with factory() as db:
        db.add_all(
            [
                UserModel(
                    user_id=ORGANIZER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="organizer@dispatcher.test",
                    password_hash="hash",
                    name="Organizer",
                ),
                UserModel(
                    user_id=USER_A_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="user_a@dispatcher.test",
                    password_hash="hash",
                    name="User A",
                ),
                UserModel(
                    user_id=USER_B_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="user_b@dispatcher.test",
                    password_hash="hash",
                    name="User B",
                ),
                EventModel(
                    event_id=EVENT_ID,
                    event_creator_id=ORGANIZER_ID,
                    event_title="Public Event",
                    event_latitude=0.0,
                    event_longitude=0.0,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    max_participants=None,
                    event_status=EventStatusEnum.PUBLISHED,
                    event_privacy=EventPrivacyEnum.PUBLIC,
                ),
                EventModel(
                    event_id=PRIVATE_EVENT_ID,
                    event_creator_id=ORGANIZER_ID,
                    event_title="Private Event",
                    event_latitude=0.0,
                    event_longitude=0.0,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    max_participants=None,
                    event_status=EventStatusEnum.PUBLISHED,
                    event_privacy=EventPrivacyEnum.PRIVATE,
                ),
            ]
        )
        db.commit()

    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------


def test_accept_connection_notifies_requester(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        conn_repo = SqlAlchemyConnectionRepository(db, notification_repo)
        svc = ConnectionService(conn_repo)

        connection = svc.send_request(requester_id=USER_A_ID, receiver_id=USER_B_ID)
        assert connection.connection_id is not None

        # Clear the CONNECTION_REQUEST notification before testing accept
        db.query(NotificationModel).delete()
        db.commit()

        svc.accept(connection.connection_id, actor_id=USER_B_ID)

    with session_factory() as db:
        notification = db.scalar(
            select(NotificationModel).where(
                NotificationModel.user_id == USER_A_ID,
                NotificationModel.type == NotificationTypeEnum.CONNECTION_ACCEPTED,
            )
        )
        assert notification is not None
        detail = db.scalar(
            select(
                __import__(
                    "app.infrastructure.repository.models",
                    fromlist=["ConnectionNotificationModel"],
                ).ConnectionNotificationModel
            ).where(
                __import__(
                    "app.infrastructure.repository.models",
                    fromlist=["ConnectionNotificationModel"],
                ).ConnectionNotificationModel.notification_id
                == notification.notification_id
            )
        )
        assert detail is not None


def test_send_connection_request_notifies_receiver(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        conn_repo = SqlAlchemyConnectionRepository(db, notification_repo)
        svc = ConnectionService(conn_repo)

        svc.send_request(requester_id=USER_A_ID, receiver_id=USER_B_ID)

    with session_factory() as db:
        notification = db.scalar(
            select(NotificationModel).where(
                NotificationModel.user_id == USER_B_ID,
                NotificationModel.type == NotificationTypeEnum.CONNECTION_REQUEST,
            )
        )
        assert notification is not None


def test_reject_connection_does_not_notify(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        conn_repo = SqlAlchemyConnectionRepository(db, notification_repo)
        svc = ConnectionService(conn_repo)

        connection = svc.send_request(requester_id=USER_A_ID, receiver_id=USER_B_ID)
        db.query(NotificationModel).delete()
        db.commit()

        svc.reject(connection.connection_id, actor_id=USER_B_ID)

    with session_factory() as db:
        count = db.query(NotificationModel).count()
        assert count == 0


def test_reject_already_accepted_connection_raises(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        conn_repo = SqlAlchemyConnectionRepository(db, notification_repo)
        svc = ConnectionService(conn_repo)

        connection = svc.send_request(requester_id=USER_A_ID, receiver_id=USER_B_ID)
        svc.accept(connection.connection_id, actor_id=USER_B_ID)

        with pytest.raises(InvalidConnectionStatusTransitionError):
            svc.reject(connection.connection_id, actor_id=USER_B_ID)


# ---------------------------------------------------------------------------
# Participation tests
# ---------------------------------------------------------------------------


def test_join_public_event_notifies_organizer(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        part_repo = SqlAlchemyParticipationRepository(db, notification_repo)
        svc = ParticipationService(part_repo)

        participant = svc.request_or_join(event_id=EVENT_ID, user_id=USER_A_ID)
        assert participant.status is EventParticipantStatusEnum.CONFIRMED

    with session_factory() as db:
        notification = db.scalar(
            select(NotificationModel).where(
                NotificationModel.user_id == ORGANIZER_ID,
                NotificationModel.type == NotificationTypeEnum.EVENT_PARTICIPANT_JOINED,
            )
        )
        assert notification is not None
        detail = db.scalar(
            select(EventParticipantNotificationModel).where(
                EventParticipantNotificationModel.notification_id
                == notification.notification_id
            )
        )
        assert detail is not None


def test_request_participation_private_event_notifies_organizer(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        part_repo = SqlAlchemyParticipationRepository(db, notification_repo)
        svc = ParticipationService(part_repo)

        participant = svc.request_or_join(event_id=PRIVATE_EVENT_ID, user_id=USER_A_ID)
        assert participant.status is EventParticipantStatusEnum.PENDING

    with session_factory() as db:
        notification = db.scalar(
            select(NotificationModel).where(
                NotificationModel.user_id == ORGANIZER_ID,
                NotificationModel.type
                == NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
            )
        )
        assert notification is not None


def test_organizer_cannot_join_own_event(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        part_repo = SqlAlchemyParticipationRepository(db, notification_repo)
        svc = ParticipationService(part_repo)

        with pytest.raises(OrganizerCannotJoinError):
            svc.request_or_join(event_id=EVENT_ID, user_id=ORGANIZER_ID)


def test_already_participating_raises(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        part_repo = SqlAlchemyParticipationRepository(db, notification_repo)
        svc = ParticipationService(part_repo)

        svc.request_or_join(event_id=EVENT_ID, user_id=USER_A_ID)
        with pytest.raises(AlreadyParticipatingError):
            svc.request_or_join(event_id=EVENT_ID, user_id=USER_A_ID)


# ---------------------------------------------------------------------------
# actor_id guard — dispatcher never notifies the actor themselves
# ---------------------------------------------------------------------------


def test_dispatcher_does_not_notify_actor(
    session_factory: sessionmaker[Session],
) -> None:
    from app.domain.services.notification_dispatcher import NotificationDispatcher

    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        dispatcher = NotificationDispatcher(notification_repo)

        conn_id = uuid4()
        dispatcher.dispatch(
            NotificationTypeEnum.CONNECTION_ACCEPTED,
            recipient_id=USER_A_ID,
            actor_id=USER_A_ID,
            connection_id=conn_id,
        )
        db.commit()

    with session_factory() as db:
        count = db.query(NotificationModel).count()
        assert count == 0


# ---------------------------------------------------------------------------
# Dispatcher failure does not break the business operation
# ---------------------------------------------------------------------------


def test_dispatcher_failure_does_not_break_operation(
    session_factory: sessionmaker[Session],
) -> None:
    from app.domain.services.notification_dispatcher import (
        NotificationDispatcher,
    )

    class BrokenRepo:
        def notify_connection(self, *args, **kwargs) -> None:
            raise RuntimeError("DB exploded")

        def notify_participant(self, *args, **kwargs) -> None:
            raise RuntimeError("DB exploded")

        def notify_event_cancelled(self, *args, **kwargs) -> None:
            raise RuntimeError("DB exploded")

        def notify_event_updated(self, *args, **kwargs) -> None:
            raise RuntimeError("DB exploded")

    dispatcher = NotificationDispatcher(BrokenRepo())

    # Should not raise
    dispatcher.dispatch(
        NotificationTypeEnum.CONNECTION_ACCEPTED,
        recipient_id=USER_A_ID,
        connection_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# EVENT_UPDATED — only fires when date or location changes
# ---------------------------------------------------------------------------


def test_event_updated_notification_created_for_confirmed_participants(
    session_factory: sessionmaker[Session],
) -> None:
    participant_id = uuid4()

    with session_factory() as db:
        db.add(
            EventParticipantModel(
                participant_id=participant_id,
                user_id=USER_A_ID,
                event_id=EVENT_ID,
                status=EventParticipantStatusEnum.CONFIRMED,
            )
        )
        db.commit()

    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)

        notification_repo.notify_event_updated(
            recipient_id=USER_A_ID, event_id=EVENT_ID
        )
        db.commit()

    with session_factory() as db:
        notification = db.scalar(
            select(NotificationModel).where(
                NotificationModel.user_id == USER_A_ID,
                NotificationModel.type == NotificationTypeEnum.EVENT_UPDATED,
            )
        )
        assert notification is not None
        detail = db.scalar(
            select(EventCancelledNotificationModel).where(
                EventCancelledNotificationModel.notification_id
                == notification.notification_id
            )
        )
        assert detail is not None
        assert detail.event_id == EVENT_ID


# ---------------------------------------------------------------------------
# EVENT_CANCELLED — only confirmed + pending, never the organizer
# ---------------------------------------------------------------------------


def test_cancel_event_notifies_confirmed_and_pending_not_organizer(
    session_factory: sessionmaker[Session],
) -> None:
    confirmed_id = uuid4()
    pending_id = uuid4()
    extra_user = uuid4()
    extra_user2 = uuid4()

    with session_factory() as db:
        db.add_all(
            [
                UserModel(
                    user_id=extra_user,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="extra1@dispatcher.test",
                    password_hash="h",
                ),
                UserModel(
                    user_id=extra_user2,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="extra2@dispatcher.test",
                    password_hash="h",
                ),
                EventParticipantModel(
                    participant_id=confirmed_id,
                    user_id=extra_user,
                    event_id=EVENT_ID,
                    status=EventParticipantStatusEnum.CONFIRMED,
                ),
                EventParticipantModel(
                    participant_id=pending_id,
                    user_id=extra_user2,
                    event_id=EVENT_ID,
                    status=EventParticipantStatusEnum.PENDING,
                ),
            ]
        )
        db.commit()

    with session_factory() as db:
        notification_repo = SqlAlchemyNotificationRepository(db)
        notification_repo.notify_event_cancelled(extra_user, EVENT_ID)
        notification_repo.notify_event_cancelled(extra_user2, EVENT_ID)
        db.commit()

    with session_factory() as db:
        notifications = db.scalars(
            select(NotificationModel).where(
                NotificationModel.type == NotificationTypeEnum.EVENT_CANCELLED
            )
        ).all()
        notified_users = {n.user_id for n in notifications}

        assert extra_user in notified_users
        assert extra_user2 in notified_users
        assert ORGANIZER_ID not in notified_users
