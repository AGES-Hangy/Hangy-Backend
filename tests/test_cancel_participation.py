import os
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
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    NotificationModel,
    UserModel,
)
from app.main import app

ORGANIZER_ID = UUID("0b2f0001-0000-4000-8000-000000000001")
OTHER_USER_ID = UUID("0b2f0001-0000-4000-8000-000000000002")
PARTICIPANT_USER_ID = UUID("0b2f0001-0000-4000-8000-000000000003")
CONFIRMED_USER_ID = UUID("0b2f0001-0000-4000-8000-000000000005")

EVENT_ID = UUID("0e000001-0000-4000-8000-000000000001")
LIMITED_EVENT_ID = UUID("0e000002-0000-4000-8000-000000000002")

PENDING_PARTICIPANT_ID = UUID("0a000001-0000-4000-8000-000000000001")
CONFIRMED_PARTICIPANT_ID = UUID("0a000003-0000-4000-8000-000000000003")


@pytest.fixture
def client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    # Optional dedicated, disposable database; never use an application DB here.
    database_url = os.environ.get("TID215_TEST_DATABASE_URL", "sqlite://")
    engine = create_engine(
        database_url,
        **(
            {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
            if database_url == "sqlite://"
            else {}
        ),
    )
    testing_session = sessionmaker(bind=engine)
    if engine.dialect.name == "postgresql":
        # Use the real migration schema (the baseline model's false() default
        # cannot be emitted by create_all on PostgreSQL).
        from unittest.mock import patch

        from alembic.config import Config

        from alembic import command

        with patch.dict(os.environ, {"DATABASE_URL": database_url}):
            command.upgrade(Config("alembic.ini"), "head")
    else:
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
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(table.delete())
    else:
        Base.metadata.drop_all(engine)
    engine.dispose()


def auth_header(user_id: UUID = ORGANIZER_ID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    "privacy,initial_status",
    [
        (EventPrivacyEnum.PUBLIC, EventParticipantStatusEnum.CONFIRMED),
        (EventPrivacyEnum.PRIVATE, EventParticipantStatusEnum.PENDING),
        (EventPrivacyEnum.PRIVATE, EventParticipantStatusEnum.CONFIRMED),
        (EventPrivacyEnum.INVITE_ONLY, EventParticipantStatusEnum.CONFIRMED),
    ],
)
def test_cancel_persists_same_row_without_notifications(
    client, privacy, initial_status
):
    http, sessions = client
    with sessions() as db:
        db.get(EventModel, EVENT_ID).event_privacy = privacy
        participant = db.get(EventParticipantModel, PENDING_PARTICIPANT_ID)
        participant.status = initial_status
        joined_at = participant.joined_at
        db.commit()
    response = http.delete(
        f"/events/{EVENT_ID}/participation", headers=auth_header(PARTICIPANT_USER_ID)
    )
    assert response.status_code == 204
    assert response.content == b""
    with sessions() as db:
        row = db.get(EventParticipantModel, PENDING_PARTICIPANT_ID)
        assert row.status == EventParticipantStatusEnum.CANCELLED
        assert row.joined_at == joined_at
        assert row.user_id == PARTICIPANT_USER_ID
        assert (
            db.get(EventParticipantModel, CONFIRMED_PARTICIPANT_ID).status
            == EventParticipantStatusEnum.CONFIRMED
        )
        assert list(db.scalars(select(NotificationModel))) == []
    page = http.get(
        f"/events/{EVENT_ID}/participants",
        params={"status": initial_status.value},
        headers=auth_header(ORGANIZER_ID),
    )
    assert page.status_code == 200
    assert str(PENDING_PARTICIPANT_ID) not in page.text


@pytest.mark.parametrize("finished_status,past_end", [(True, False), (False, True)])
def test_finished_confirmed_event_is_409_and_unchanged(
    client, finished_status, past_end
):
    http, sessions = client
    with sessions() as db:
        event = db.get(EventModel, EVENT_ID)
        if finished_status:
            event.event_status = EventStatusEnum.FINISHED
        if past_end:
            event.ends_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    response = http.delete(
        f"/events/{EVENT_ID}/participation", headers=auth_header(CONFIRMED_USER_ID)
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Event already finished"}
    with sessions() as db:
        assert (
            db.get(EventParticipantModel, CONFIRMED_PARTICIPANT_ID).status
            == EventParticipantStatusEnum.CONFIRMED
        )


@pytest.mark.parametrize(
    "participant_status",
    [EventParticipantStatusEnum.REJECTED, EventParticipantStatusEnum.REMOVED],
)
def test_answered_request_is_409_and_unchanged(client, participant_status):
    http, sessions = client
    with sessions() as db:
        db.get(
            EventParticipantModel, PENDING_PARTICIPANT_ID
        ).status = participant_status
        db.commit()
    response = http.delete(
        f"/events/{EVENT_ID}/participation", headers=auth_header(PARTICIPANT_USER_ID)
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Request already answered"}
    with sessions() as db:
        assert (
            db.get(EventParticipantModel, PENDING_PARTICIPANT_ID).status
            == participant_status
        )
        assert list(db.scalars(select(NotificationModel))) == []


@pytest.mark.parametrize(
    "case",
    ["missing_event", "missing_participant", "deleted_event", "already_cancelled"],
)
def test_missing_participation_is_404(client, case):
    http, sessions = client
    event_id, user_id = EVENT_ID, PARTICIPANT_USER_ID
    with sessions() as db:
        if case == "missing_event":
            event_id = uuid4()
        elif case == "missing_participant":
            user_id = OTHER_USER_ID
        elif case == "deleted_event":
            db.get(EventModel, EVENT_ID).deleted_at = datetime.now(UTC)
        else:
            db.get(
                EventParticipantModel, PENDING_PARTICIPANT_ID
            ).status = EventParticipantStatusEnum.CANCELLED
        db.commit()
    response = http.delete(
        f"/events/{event_id}/participation", headers=auth_header(user_id)
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Participant not found"}
    with sessions() as db:
        assert (
            db.get(EventParticipantModel, CONFIRMED_PARTICIPANT_ID).status
            == EventParticipantStatusEnum.CONFIRMED
        )


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_authentication_required(client, headers):
    http, sessions = client
    assert (
        http.delete(f"/events/{EVENT_ID}/participation", headers=headers).status_code
        == 401
    )
    with sessions() as db:
        assert (
            db.get(EventParticipantModel, PENDING_PARTICIPANT_ID).status
            == EventParticipantStatusEnum.PENDING
        )


def test_cancel_frees_capacity_for_organizer_approval(client):
    http, sessions = client
    with sessions() as db:
        db.get(EventModel, EVENT_ID).max_participants = 1
        db.commit()
    url = f"/events/{EVENT_ID}/participants/{PENDING_PARTICIPANT_ID}"
    assert (
        http.patch(url, json={"status": "CONFIRMED"}, headers=auth_header()).status_code
        == 409
    )
    assert (
        http.delete(
            f"/events/{EVENT_ID}/participation", headers=auth_header(CONFIRMED_USER_ID)
        ).status_code
        == 204
    )
    assert (
        http.patch(url, json={"status": "CONFIRMED"}, headers=auth_header()).status_code
        == 200
    )


def test_pending_request_can_be_withdrawn_after_event_ends(client):
    http, sessions = client
    with sessions() as db:
        db.get(EventModel, EVENT_ID).event_status = EventStatusEnum.FINISHED
        db.commit()
    assert (
        http.delete(
            f"/events/{EVENT_ID}/participation",
            headers=auth_header(PARTICIPANT_USER_ID),
        ).status_code
        == 204
    )


def test_openapi_has_no_request_or_response_body(client):
    http, _ = client
    operation = http.get("/openapi.json").json()["paths"][
        "/events/{event_id}/participation"
    ]["delete"]
    assert set(operation["responses"]) >= {"204", "401", "404", "409"}
    assert "requestBody" not in operation
    assert "content" not in operation["responses"]["204"]


def test_database_failure_does_not_cancel_participation(client):
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError

    http, sessions = client
    engine = sessions.kw["bind"]

    def fail_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE event_participant"):
            raise SQLAlchemyError("Injected persistence failure")

    event.listen(engine, "before_cursor_execute", fail_update)
    try:
        with pytest.raises(SQLAlchemyError):
            http.delete(
                f"/events/{EVENT_ID}/participation",
                headers=auth_header(PARTICIPANT_USER_ID),
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_update)
    with sessions() as db:
        assert (
            db.get(EventParticipantModel, PENDING_PARTICIPANT_ID).status
            == EventParticipantStatusEnum.PENDING
        )


def test_postgres_cancel_observes_committed_organizer_decision(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import event

    http, sessions = client
    engine = sessions.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("Requires disposable PostgreSQL for row-lock semantics")
    waiting = Event()

    def observe_lock(conn, cursor, statement, parameters, context, executemany):
        if "FOR UPDATE" in statement and "FROM event" in statement:
            waiting.set()

    with sessions() as organizer:
        organizer.scalar(
            select(EventModel).where(EventModel.event_id == EVENT_ID).with_for_update()
        )
        organizer.get(
            EventParticipantModel, PENDING_PARTICIPANT_ID
        ).status = EventParticipantStatusEnum.REJECTED
        organizer.flush()
        event.listen(engine, "before_cursor_execute", observe_lock)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                request = pool.submit(
                    http.delete,
                    f"/events/{EVENT_ID}/participation",
                    headers=auth_header(PARTICIPANT_USER_ID),
                )
                try:
                    assert waiting.wait(5), "DELETE never attempted the event lock"
                    assert not request.done()
                finally:
                    organizer.commit()
                response = request.result(timeout=5)
        finally:
            event.remove(engine, "before_cursor_execute", observe_lock)
    assert response.status_code == 409
    assert response.json() == {"detail": "Request already answered"}
    with sessions() as db:
        assert (
            db.get(EventParticipantModel, PENDING_PARTICIPANT_ID).status
            == EventParticipantStatusEnum.REJECTED
        )


def test_postgres_concurrent_cancellations_only_one_succeeds(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    http, sessions = client
    if sessions.kw["bind"].dialect.name != "postgresql":
        pytest.skip("Requires disposable PostgreSQL for row-lock semantics")
    barrier = Barrier(2)

    def cancel():
        barrier.wait(timeout=5)
        return http.delete(
            f"/events/{EVENT_ID}/participation", headers=auth_header(CONFIRMED_USER_ID)
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: cancel(), range(2)))
    assert sorted(results) == [204, 404]
    with sessions() as db:
        assert (
            db.get(EventParticipantModel, CONFIRMED_PARTICIPANT_ID).status
            == EventParticipantStatusEnum.CANCELLED
        )
        assert list(db.scalars(select(NotificationModel))) == []


@pytest.mark.parametrize(
    "user_id,participant_id,privacy,expected",
    [
        (
            CONFIRMED_USER_ID,
            CONFIRMED_PARTICIPANT_ID,
            EventPrivacyEnum.PUBLIC,
            EventParticipantStatusEnum.CONFIRMED,
        ),
        (
            PARTICIPANT_USER_ID,
            PENDING_PARTICIPANT_ID,
            EventPrivacyEnum.PRIVATE,
            EventParticipantStatusEnum.PENDING,
        ),
    ],
)
def test_cancel_then_rejoin_with_task105(
    client, user_id, participant_id, privacy, expected
):
    http, sessions = client
    operations = http.get("/openapi.json").json()["paths"][
        "/events/{event_id}/participation"
    ]
    if "post" not in operations:
        pytest.skip("Rejoin integration requires task 105 POST endpoint")
    with sessions() as db:
        db.get(EventModel, EVENT_ID).event_privacy = privacy
        db.commit()
    url = f"/events/{EVENT_ID}/participation"
    assert http.delete(url, headers=auth_header(user_id)).status_code == 204
    response = http.post(url, headers=auth_header(user_id))
    assert response.status_code in (200, 201), response.text
    with sessions() as db:
        rows = list(
            db.scalars(
                select(EventParticipantModel).where(
                    EventParticipantModel.event_id == EVENT_ID,
                    EventParticipantModel.user_id == user_id,
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].participant_id == participant_id
        assert rows[0].status == expected
