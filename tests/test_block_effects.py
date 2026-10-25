"""Bilateral blocking contract, using a disposable DB and synthetic users only."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import EventParticipantStatusEnum as Status
from app.domain.enums import EventPrivacyEnum as Privacy
from app.domain.enums import NotificationTypeEnum as Type
from app.domain.enums import UserConnectionStatusEnum
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    ConnectionNotificationModel,
    EventCancelledNotificationModel,
    EventInviteLinkModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    NotificationModel,
    UserBlockModel,
    UserConnectionModel,
)
from app.infrastructure.repository.notification import SqlAlchemyNotificationRepository
from app.main import app
from tests.test_event_participation import (
    _add_event,
    _add_participant,
    _add_user,
    _authorization,
)


@pytest.fixture
def blocked_env():
    url = os.getenv("HANGY_BLOCK_TEST_DATABASE_URL", "sqlite://")
    options = (
        {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        if url == "sqlite://"
        else {}
    )
    engine = create_engine(url, **options)
    if url == "sqlite://":
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override
    a, b, c = uuid4(), uuid4(), uuid4()
    with factory() as db:
        for uid, name in ((a, "Ana"), (b, "Bruno"), (c, "Carla")):
            _add_user(db, uid, name)
        db.commit()
    with TestClient(app) as client:
        yield client, factory, a, b, c
    app.dependency_overrides.clear()
    if url == "sqlite://":
        Base.metadata.drop_all(engine)
    else:
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())
    engine.dispose()


def block(client, a, b):
    assert (
        client.post(f"/users/{b}/block", headers=_authorization(a)).status_code == 204
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("privacy", list(Privacy))
def test_deny_every_entry_and_allow_explicit_rejoin_after_unblock(
    blocked_env, reverse, privacy
):
    client, sf, a, b, _ = blocked_env
    organizer, guest = (b, a) if reverse else (a, b)
    event = uuid4()
    token = f"invite-{uuid4()}"
    with sf() as db:
        _add_event(db, event, organizer, privacy)
        db.add(
            EventInviteLinkModel(
                event_id=event,
                created_by=organizer,
                token=token,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        db.commit()
    path = (
        f"/invites/{token}/accept"
        if privacy == Privacy.INVITE_ONLY
        else f"/events/{event}/participation"
    )
    accepted = 200 if privacy == Privacy.INVITE_ONLY else 201
    assert client.post(path, headers=_authorization(guest)).status_code == accepted
    block(client, a, b)
    assert (
        client.get(f"/events/{event}", headers=_authorization(guest)).status_code == 404
    )
    assert client.post(path, headers=_authorization(guest)).status_code == 404
    with sf() as db:
        assert db.scalar(select(EventParticipantModel)).status == Status.CANCELLED
        assert db.scalars(select(NotificationModel)).all() == []
    assert (
        client.delete(f"/users/{b}/block", headers=_authorization(a)).status_code == 204
    )
    with sf() as db:
        assert db.scalar(select(EventParticipantModel)).status == Status.CANCELLED
        assert db.scalars(select(NotificationModel)).all() == []
    assert client.post(path, headers=_authorization(guest)).status_code == accepted


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("status", [Status.PENDING, Status.CONFIRMED])
def test_remove_existing_and_deny_old_approval_preserving_third_party(
    blocked_env, reverse, status
):
    client, sf, a, b, c = blocked_env
    organizer, guest = (b, a) if reverse else (a, b)
    event = uuid4()
    with sf() as db:
        _add_event(db, event, organizer, Privacy.PRIVATE)
        _add_participant(db, event, guest, status)
        _add_participant(db, event, c, Status.CONFIRMED)
        db.commit()
        pid = db.scalar(
            select(EventParticipantModel.participant_id).where(
                EventParticipantModel.user_id == guest
            )
        )
    block(client, a, b)
    with sf() as db:
        assert db.get(EventParticipantModel, pid).status == Status.CANCELLED
        assert (
            db.scalar(
                select(EventParticipantModel.status).where(
                    EventParticipantModel.user_id == c
                )
            )
            == Status.CONFIRMED
        )
    response = client.patch(
        f"/events/{event}/participants/{pid}",
        headers=_authorization(organizer),
        json={"status": "CONFIRMED"},
    )
    assert response.status_code == 404


def add_notification(db, kind, recipient, connection, participant, event):
    n = NotificationModel(
        user_id=recipient, type=kind, read=kind == Type.CONNECTION_ACCEPTED
    )
    db.add(n)
    db.flush()
    if kind in (Type.CONNECTION_REQUEST, Type.CONNECTION_ACCEPTED):
        detail = ConnectionNotificationModel(
            notification_id=n.notification_id, connection_id=connection
        )
    elif kind in (Type.EVENT_CANCELLED, Type.EVENT_UPDATED):
        detail = EventCancelledNotificationModel(
            notification_id=n.notification_id, event_id=event
        )
    else:
        detail = EventParticipantNotificationModel(
            notification_id=n.notification_id, participant_id=participant
        )
    db.add(detail)
    return n.notification_id


@pytest.mark.parametrize("recipient_is_organizer", [False, True])
def test_delete_all_types_both_directions_and_suppress_future_dispatch(
    blocked_env, recipient_is_organizer
):
    client, sf, a, b, c = blocked_env
    if recipient_is_organizer:
        a, b = b, a
    event = uuid4()
    other_event = uuid4()
    with sf() as db:
        _add_event(db, event, a, Privacy.PUBLIC)
        _add_event(db, other_event, c, Privacy.PUBLIC)
        _add_participant(db, event, b, Status.CONFIRMED)
        _add_participant(db, other_event, a, Status.CONFIRMED)
        conn = UserConnectionModel(
            requester_id=a,
            receiver_id=b,
            status=UserConnectionStatusEnum.CONFIRMED,
            deleted_at=datetime.now(UTC),
        )
        db.add(conn)
        db.flush()
        pid = db.scalar(
            select(EventParticipantModel.participant_id).where(
                EventParticipantModel.user_id == b
            )
        )
        other_pid = db.scalar(
            select(EventParticipantModel.participant_id).where(
                EventParticipantModel.user_id == a
            )
        )
        organizer_types = {
            Type.EVENT_PARTICIPATION_REQUEST,
            Type.EVENT_PARTICIPANT_JOINED,
            Type.EVENT_PARTICIPANT_CANCELLED,
            Type.CONNECTION_ACCEPTED,
        }

        def recipient_for(kind):
            return a if kind in organizer_types else b

        for kind in Type:
            add_notification(
                db, kind, recipient_for(kind), conn.connection_id, pid, event
            )
        kept = add_notification(
            db, Type.EVENT_STARTING_SOON, a, conn.connection_id, other_pid, other_event
        )
        kept_third = add_notification(
            db, Type.EVENT_UPDATED, c, conn.connection_id, pid, event
        )
        db.commit()
        cid = conn.connection_id
    block(client, a, b)
    with sf() as db:
        assert set(db.scalars(select(NotificationModel.notification_id))) == {
            kept,
            kept_third,
        }
        repository = SqlAlchemyNotificationRepository(db)
        for kind in Type:
            recipient = recipient_for(kind)
            if kind in (Type.CONNECTION_REQUEST, Type.CONNECTION_ACCEPTED):
                assert repository.notify_connection(recipient, cid, kind) is None
            elif kind == Type.EVENT_CANCELLED:
                assert repository.notify_event_cancelled(b, event) is None
            elif kind == Type.EVENT_UPDATED:
                assert repository.notify_event_updated(b, event) is None
            else:
                assert repository.notify_participant(recipient, pid, kind) is None
        db.commit()
        assert set(db.scalars(select(NotificationModel.notification_id))) == {
            kept,
            kept_third,
        }
    for uid, expected in ((a, 1), (b, 0)):
        response = client.get("/notifications", headers=_authorization(uid))
        assert response.status_code == 200
        assert len(response.json()["items"]) == expected
        assert (
            client.get(
                "/notifications/unread-count", headers=_authorization(uid)
            ).json()["unread_count"]
            == expected
        )


def test_legacy_repeat_block_repairs_effects_and_keeps_409(blocked_env):
    client, sf, a, b, _ = blocked_env
    event = uuid4()
    with sf() as db:
        _add_event(db, event, a, Privacy.PRIVATE)
        _add_participant(db, event, b, Status.PENDING)
        db.add(UserBlockModel(blocker_id=a, blocked_id=b))
        db.commit()
    assert (
        client.post(f"/users/{b}/block", headers=_authorization(a)).status_code == 409
    )
    with sf() as db:
        assert db.scalar(select(EventParticipantModel)).status == Status.CANCELLED


def test_cleanup_failure_rolls_back_block_and_participation(blocked_env, monkeypatch):
    client, sf, a, b, _ = blocked_env
    event = uuid4()
    with sf() as db:
        _add_event(db, event, a, Privacy.PRIVATE)
        _add_participant(db, event, b, Status.PENDING)
        db.commit()

    def fail(*args):
        raise RuntimeError("injected cleanup failure")

    monkeypatch.setattr(
        "app.infrastructure.repository.block.delete_pair_notifications", fail
    )
    with pytest.raises(RuntimeError, match="injected cleanup failure"):
        block(client, a, b)
    with sf() as db:
        assert db.scalars(select(UserBlockModel)).all() == []
        assert db.scalar(select(EventParticipantModel)).status == Status.PENDING


@pytest.mark.parametrize("entry_first", [False, True])
def test_postgres_block_serializes_with_entry(blocked_env, monkeypatch, entry_first):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import app.infrastructure.repository.block as block_module
    from app.domain.services.notification_dispatcher import NotificationDispatcher
    from app.domain.services.participation import (
        EventNotFoundError,
        ParticipationService,
    )
    from app.infrastructure.repository.block import SqlAlchemyBlockRepository
    from app.infrastructure.repository.participation import (
        SqlAlchemyParticipationRepository,
    )

    _, sf, a, b, _ = blocked_env
    if sf.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Requires the disposable migrated PostgreSQL database")
    event = uuid4()
    with sf() as db:
        _add_event(db, event, a, Privacy.PUBLIC)
        db.commit()
    acquired, release = Event(), Event()
    if entry_first:
        original = SqlAlchemyParticipationRepository.upsert_participation

        def pause(self, *args, **kwargs):
            acquired.set()
            assert release.wait(5)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(
            SqlAlchemyParticipationRepository, "upsert_participation", pause
        )
    else:
        original = block_module.delete_pair_notifications

        def pause(*args):
            acquired.set()
            assert release.wait(5)
            return original(*args)

        monkeypatch.setattr(block_module, "delete_pair_notifications", pause)

    def join():
        with sf() as db:
            service = ParticipationService(
                SqlAlchemyParticipationRepository(
                    db, NotificationDispatcher(SqlAlchemyNotificationRepository(db))
                )
            )
            try:
                service.request_or_join(event, b)
                return "joined"
            except EventNotFoundError:
                return "blocked"

    def create_block():
        with sf() as db:
            SqlAlchemyBlockRepository(db).create(a, b)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(join if entry_first else create_block)
        assert acquired.wait(5)
        from concurrent.futures import TimeoutError

        started = Event()

        def second_operation():
            started.set()
            return create_block() if entry_first else join()

        second = pool.submit(second_operation)
        assert started.wait(5)
        with pytest.raises(TimeoutError):
            second.result(timeout=0.1)
        release.set()
        one, two = first.result(timeout=8), second.result(timeout=8)
        assert (one if entry_first else two) == ("joined" if entry_first else "blocked")
    with sf() as db:
        assert all(
            row.status == Status.CANCELLED
            for row in db.scalars(select(EventParticipantModel))
        )
        assert db.scalars(select(NotificationModel)).all() == []
