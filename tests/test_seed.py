from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    UserConnectionStatusEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventCancelledNotificationModel,
    EventInviteLinkModel,
    EventModel,
    EventParticipantModel,
    NotificationModel,
    TagModel,
    UserConnectionModel,
    UserModel,
    user_tag,
)
from app.main import app
from app.seed import (
    SEED_EVENTS,
    SEED_INTERESTS,
    SEED_NOTIFICATIONS,
    SEED_TAGS,
    SEED_USERS,
    seed_event_id,
    seed_events,
    seed_notification_id,
    seed_notifications,
    seed_tags,
    seed_user_interests,
    seed_users,
)

# Every macro tag plus the micro tags that hang below it.
SEED_TAG_COUNT = len(SEED_TAGS) + sum(len(micros) for micros in SEED_TAGS.values())


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine)
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed_everything(db: Session) -> None:
    seed_users(db)
    seed_tags(db)
    seed_user_interests(db)
    seed_events(db)
    seed_notifications(db)


def count(db: Session, entity: object) -> int:
    return db.scalar(select(func.count()).select_from(entity))


def test_seed_creates_the_sample_data_only_once(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        seed_everything(db)

        users = db.scalars(select(UserModel).order_by(UserModel.email)).all()
        tags = db.scalars(select(TagModel.tag_name)).all()

        assert [user.email for user in users] == sorted(
            credentials.email for credentials in SEED_USERS
        )
        assert all(user.password_hash for user in users)
        assert len(tags) == SEED_TAG_COUNT
        assert count(db, EventModel) == len(SEED_EVENTS)
        assert count(db, EventInviteLinkModel) == 1
        assert count(db, user_tag) == sum(
            len(tag_names) for tag_names in SEED_INTERESTS.values()
        )
        assert count(db, EventParticipantModel) == 12
        assert count(db, NotificationModel) == len(SEED_NOTIFICATIONS)


def test_seed_creates_a_reusable_invite_only_link(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

        invite_link = db.scalar(select(EventInviteLinkModel))
        assert invite_link is not None
        assert invite_link.token == "seed-invite-racha-fechado"
        assert invite_link.event.event_title == "Rachão fechado"
        assert invite_link.expires_at == invite_link.event.starts_at


def test_seed_backfills_missing_locations_and_preserves_existing_names(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        events = db.scalars(select(EventModel)).all()
        assert all(event.location_name for event in events)

        missing, customized = events[:2]
        expected_location = missing.location_name
        missing.location_name = None
        customized.location_name = "Local atualizado"
        db.commit()

        seed_events(db)
        db.refresh(missing)
        db.refresh(customized)

        assert missing.location_name == expected_location
        assert customized.location_name == "Local atualizado"
        assert count(db, EventModel) == len(SEED_EVENTS)


def test_seed_does_not_modify_an_existing_event_with_the_same_title(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_users(db)
        seed_tags(db)
        creator = db.scalar(
            select(UserModel).where(UserModel.email == SEED_EVENTS[0].creator_email)
        )
        starts_at = datetime.now(UTC) + timedelta(days=30)
        event = EventModel(
            event_creator_id=creator.user_id,
            event_title=SEED_EVENTS[0].title,
            event_latitude=-30.0,
            event_longitude=-51.0,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=2),
            event_status=SEED_EVENTS[0].event_status,
            event_privacy=SEED_EVENTS[0].privacy,
        )
        db.add(event)
        db.commit()
        original_start = event.starts_at
        original_end = event.ends_at

        seed_events(db)
        seed_events(db)
        db.refresh(event)

        assert event.starts_at == original_start
        assert event.ends_at == original_end
        assert event.participants == []
        assert count(db, EventModel) == len(SEED_EVENTS) + 1


def test_seed_tags_creates_the_default_macro_and_micro_tags_only_once(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_tags(db)
        seed_tags(db)

        macros = db.scalars(
            select(TagModel).where(TagModel.tag_parent_id.is_(None))
        ).all()

        assert sorted(macro.tag_name for macro in macros) == sorted(SEED_TAGS)

        for macro in macros:
            micro_names = db.scalars(
                select(TagModel.tag_name).where(TagModel.tag_parent_id == macro.tag_id)
            ).all()
            assert sorted(micro_names) == sorted(SEED_TAGS[macro.tag_name])


def test_seed_hangs_every_micro_tag_below_a_macro_tag(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

        football = db.scalar(select(TagModel).where(TagModel.tag_name == "Futebol"))

        assert football is not None
        assert football.parent is not None
        assert football.parent.tag_name == "Esportes"
        assert football.parent.tag_parent_id is None


def test_seeded_feed_matches_the_documented_sample(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": "user@hangy.com", "password": "user-password"},
        )
        assert login.status_code == 200
        response = client.get(
            "/feed",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    sections = response.json()["sections"]
    assert [section["tag"]["name"] for section in sections] == ["Esportes", "Música"]

    sports = [
        (item["title"], item["participants_count"], item["event_date"] is None)
        for item in sections[0]["items"]
    ]
    assert sports == [
        ("Pelada no Parcão", 3, False),
        # Both PRIVATE: discoverable, but the schedule stays hidden — even
        # from "Corrida da Redenção"'s own creator, user@hangy.com.
        ("Aniversário da Maria", 1, True),
        # Only the confirmed one counts: Ana cancelled and João is still pending.
        ("Corrida da Redenção", 1, True),
        # admin@hangy.com's own PRIVATE event, with nobody in it.
        ("Confraternização da equipe", 0, True),
    ]
    assert [item["title"] for item in sections[1]["items"]] == [
        "Show de rock no Opinião"
    ]


def test_seeded_business_user_has_an_empty_feed(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": "admin@hangy.com", "password": "admin-password"},
        )
        response = client.get(
            "/feed",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    app.dependency_overrides.clear()

    assert response.json() == {"sections": []}


@pytest.mark.parametrize(
    ("email", "password", "expected"),
    [
        (
            "pedro@hangy.com",
            "pedro-password",
            [
                ("Arte e Cultura", "Teatro"),
                ("Esportes", "Futebol"),
                ("Gastronomia", "Churrasco"),
                ("Gastronomia", "Confeitaria"),
                ("Música", "Sertanejo"),
            ],
        ),
        ("ana@hangy.com", "ana-password", []),
    ],
)
def test_seeded_user_tags_match_the_documented_sample(
    session_factory: sessionmaker[Session],
    email: str,
    password: str,
    expected: list[tuple[str, str]],
) -> None:
    with session_factory() as db:
        seed_everything(db)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200
        response = client.get(
            "/users/me/tags",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [
        (tag["parent"]["name"], tag["name"]) for tag in response.json()["tags"]
    ] == expected


def test_seeded_notifications_feed_the_unread_count(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        seed_everything(db)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": "user@hangy.com", "password": "user-password"},
        )
        assert login.status_code == 200
        response = client.get(
            "/notifications/unread-count",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"unread_count": 10}


def test_seed_gives_user_every_notification_type_with_its_payload(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        seed_everything(db)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": "user@hangy.com", "password": "user-password"},
        )
        response = client.get(
            "/notifications",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["type"] for item in items} == {
        notification_type.value for notification_type in NotificationTypeEnum
    }
    assert response.json()["unread_count"] == 10
    assert all(item["payload"] for item in items)

    connection_senders = {
        (item["type"], item["payload"]["sender"]["name"])
        for item in items
        if item["type"].startswith("CONNECTION_")
    }
    assert connection_senders == {
        ("CONNECTION_REQUEST", "Maria Silva"),
        ("CONNECTION_REQUEST", "João Souza"),
        ("CONNECTION_REQUEST", "Ana Costa"),
        ("CONNECTION_REQUEST", "Pedro Lima"),
        ("CONNECTION_REQUEST", "Carla Dias"),
        ("CONNECTION_ACCEPTED", "Lucas Rocha"),
        ("CONNECTION_ACCEPTED", "Bia Martins"),
    }

    payloads = {item["type"]: item["payload"] for item in items}
    assert payloads["EVENT_PARTICIPATION_REQUEST"]["event_title"] == (
        "Corrida da Redenção"
    )
    assert payloads["EVENT_REQUEST_APPROVED"]["sender"]["name"] == "Maria Silva"
    assert payloads["EVENT_UPDATED"]["event_title"] == "Pelada no Parcão"
    assert payloads["EVENT_CANCELLED"]["event_title"] == "Pelada"


def test_seeded_notifications_match_the_state_they_describe(
    session_factory: sessionmaker[Session],
) -> None:
    participant_status = {
        NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST: (
            EventParticipantStatusEnum.PENDING
        ),
        NotificationTypeEnum.EVENT_PARTICIPANT_JOINED: (
            EventParticipantStatusEnum.CONFIRMED
        ),
        NotificationTypeEnum.EVENT_STARTING_SOON: EventParticipantStatusEnum.CONFIRMED,
        NotificationTypeEnum.EVENT_REQUEST_APPROVED: (
            EventParticipantStatusEnum.CONFIRMED
        ),
        NotificationTypeEnum.EVENT_REQUEST_REJECTED: (
            EventParticipantStatusEnum.REJECTED
        ),
        NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED: (
            EventParticipantStatusEnum.CANCELLED
        ),
        NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED: (
            EventParticipantStatusEnum.REMOVED
        ),
    }
    # Who receives it: the event's creator, or the participant themself.
    recipient_is_creator = {
        NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
        NotificationTypeEnum.EVENT_PARTICIPANT_JOINED,
        NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED,
    }

    with session_factory() as db:
        seed_everything(db)
        seed_everything(db)

        for notification in db.scalars(select(NotificationModel)):
            kind = notification.type
            if kind in participant_status:
                detail = notification.participant_detail
                assert detail is not None, kind
                participant = detail.participant
                assert participant.status == participant_status[kind], kind
                if kind in recipient_is_creator:
                    assert participant.event.event_creator_id == notification.user_id
                    assert participant.user_id != notification.user_id
                else:
                    assert participant.user_id == notification.user_id
                    assert participant.event.event_creator_id != notification.user_id
            elif kind == NotificationTypeEnum.EVENT_CANCELLED:
                detail = notification.event_cancelled_detail
                assert detail is not None
                assert detail.event.event_status == EventStatusEnum.CANCELLED
            elif kind == NotificationTypeEnum.EVENT_UPDATED:
                assert notification.event_cancelled_detail is not None
            else:
                detail = notification.connection_detail
                assert detail is not None, kind
                connection = detail.connection
                if kind == NotificationTypeEnum.CONNECTION_REQUEST:
                    assert connection.status == UserConnectionStatusEnum.PENDING
                    assert connection.receiver_id == notification.user_id
                else:
                    assert connection.status == UserConnectionStatusEnum.CONFIRMED
                    assert connection.requester_id == notification.user_id

        # A pair is connected in one direction only, so no pending request
        # contradicts an accepted one.
        pairs = [
            frozenset((c.requester_id, c.receiver_id))
            for c in db.scalars(select(UserConnectionModel))
        ]
        assert len(pairs) == len(set(pairs))


def test_seed_restores_participants_changed_while_testing(
    session_factory: sessionmaker[Session],
) -> None:
    event_id = seed_event_id("user@hangy.com", "Corrida da Redenção")
    with session_factory() as db:
        seed_everything(db)
        joao = db.scalar(select(UserModel).where(UserModel.email == "joao@hangy.com"))
        maria = db.scalar(select(UserModel).where(UserModel.email == "maria@hangy.com"))
        participants = {
            p.user_id: p
            for p in db.scalars(
                select(EventParticipantModel).where(
                    EventParticipantModel.event_id == event_id
                )
            )
        }
        participants[joao.user_id].status = EventParticipantStatusEnum.REMOVED
        participants[maria.user_id].status = EventParticipantStatusEnum.REMOVED
        db.commit()

        seed_everything(db)
        db.expire_all()

        assert participants[joao.user_id].status == EventParticipantStatusEnum.PENDING
        assert (
            participants[maria.user_id].status == EventParticipantStatusEnum.CONFIRMED
        )
        assert count(db, EventParticipantModel) == 12


def test_seed_recomputes_notification_dates_from_the_current_time(
    session_factory: sessionmaker[Session],
) -> None:
    notification_id = seed_notification_id("user@hangy.com", "connection-request")
    with session_factory() as db:
        seed_everything(db)
        notification = db.get(NotificationModel, notification_id)
        notification.created_at = datetime.now(UTC) - timedelta(days=30)
        db.commit()

        seed_everything(db)
        db.refresh(notification)

        age = datetime.now(UTC) - notification.created_at.replace(tzinfo=UTC)
        assert age < timedelta(hours=1)


def test_seed_backfills_the_payload_of_notifications_created_without_details(
    session_factory: sessionmaker[Session],
) -> None:
    notification_id = seed_notification_id("user@hangy.com", "event-updated")
    with session_factory() as db:
        seed_everything(db)
        db.execute(delete(EventCancelledNotificationModel))
        db.commit()

        seed_everything(db)

        assert db.get(EventCancelledNotificationModel, notification_id) is not None


def test_seed_resets_only_the_demo_notification_to_unread(
    session_factory: sessionmaker[Session],
) -> None:
    demo_id = seed_notification_id("joao@hangy.com", "mark-as-read")
    user_notification_id = seed_notification_id(
        "user@hangy.com", "participation-request"
    )
    with session_factory() as db:
        seed_everything(db)
        db.get(NotificationModel, demo_id).read = True
        db.get(NotificationModel, user_notification_id).read = True
        db.commit()

        seed_everything(db)

        assert db.get(NotificationModel, demo_id).read is False
        assert db.get(NotificationModel, user_notification_id).read is True
