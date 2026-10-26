from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    UserConnectionStatusEnum,
)
from app.domain.services.event_location import approximate_point
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    ConnectionNotificationModel,
    EventCancelledNotificationModel,
    EventExperienceModel,
    EventInviteLinkModel,
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    ExperienceImagesModel,
    NotificationModel,
    TagModel,
    UserBlockModel,
    UserConnectionModel,
    UserFollowModel,
    UserModel,
    event_tag,
    user_tag,
)
from app.main import app
from app.seed import (
    SEED_BLOCKS,
    SEED_EVENTS,
    SEED_EXPERIENCES,
    SEED_FOLLOWS,
    SEED_INTERESTS,
    SEED_NOTIFICATIONS,
    SEED_TAGS,
    SEED_USERS,
    seed_event_id,
    seed_events,
    seed_experiences,
    seed_notification_id,
    seed_notifications,
    seed_social,
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
    seed_social(db)
    seed_experiences(db)


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
        assert count(db, EventParticipantModel) == 23
        assert count(db, NotificationModel) == len(SEED_NOTIFICATIONS)
        assert count(db, UserFollowModel) == sum(map(len, SEED_FOLLOWS.values()))
        assert count(db, UserBlockModel) == len(SEED_BLOCKS)
        assert count(db, EventExperienceModel) == len(SEED_EXPERIENCES)
        assert count(db, ExperienceImagesModel) == sum(
            len(experience.photo_urls) for experience in SEED_EXPERIENCES
        )


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


def test_seed_links_repeated_micro_names_to_the_intended_macro(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

        running = db.scalars(
            select(TagModel).where(TagModel.tag_name == "Corrida")
        ).all()
        assert sorted(tag.parent.tag_name for tag in running) == ["Esportes", "Jogos"]

        user = db.scalar(select(UserModel).where(UserModel.email == "user@hangy.com"))
        interests = {(tag.parent.tag_name, tag.tag_name) for tag in user.tags}
        assert ("Esportes", "Corrida") in interests
        assert ("Jogos", "Corrida") not in interests

        event = db.get(
            EventModel, seed_event_id("user@hangy.com", "Corrida da Redenção")
        )
        assert [(tag.parent.tag_name, tag.tag_name) for tag in event.tags] == [
            ("Esportes", "Corrida")
        ]


def test_seed_moves_users_and_events_off_the_legacy_tags(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_users(db)
        music = TagModel(tag_name="Música")
        culture = TagModel(tag_name="Arte e Cultura")
        db.add_all([music, culture])
        db.flush()
        rock = TagModel(tag_name="Rock", tag_parent_id=music.tag_id)
        theater = TagModel(tag_name="Teatro", tag_parent_id=culture.tag_id)
        db.add_all([rock, theater])
        db.flush()
        users = {user.email: user for user in db.scalars(select(UserModel))}
        creator = users["joao@hangy.com"]
        starts_at = datetime.now(UTC) + timedelta(days=30)
        own_event = EventModel(
            event_creator_id=creator.user_id,
            event_title="Evento criado pelo usuário",
            event_latitude=-30.0,
            event_longitude=-51.0,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=2),
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=SEED_EVENTS[0].privacy,
        )
        own_event.tags = [rock, theater]
        db.add(own_event)
        users["carla@hangy.com"].tags = [rock]
        db.commit()
        event_id = own_event.event_id

        seed_everything(db)
        seed_everything(db)

        names = set(
            db.execute(
                select(TagModel.tag_name).where(TagModel.tag_parent_id.is_(None))
            ).scalars()
        )
        assert names == set(SEED_TAGS)
        assert count(db, TagModel) == SEED_TAG_COUNT

        event = db.get(EventModel, event_id)
        assert sorted((tag.parent.tag_name, tag.tag_name) for tag in event.tags) == [
            ("Arte & Cultura", "Teatro"),
            ("Vida Social", "Rock"),
        ]
        carla = db.scalar(select(UserModel).where(UserModel.email == "carla@hangy.com"))
        assert [(tag.parent.tag_name, tag.tag_name) for tag in carla.tags] == [
            ("Vida Social", "Rock")
        ]
        expected_interests = 1 + sum(
            len(tag_keys) for tag_keys in SEED_INTERESTS.values()
        )
        assert count(db, user_tag) == expected_interests

        # user@hangy.com already has the new Rock: the legacy link is dropped,
        # not doubled.
        legacy_music = TagModel(tag_name="Música")
        db.add(legacy_music)
        db.flush()
        legacy_rock = TagModel(tag_name="Rock", tag_parent_id=legacy_music.tag_id)
        db.add(legacy_rock)
        db.flush()
        db.execute(
            user_tag.insert().values(
                user_id=users["user@hangy.com"].user_id, tag_id=legacy_rock.tag_id
            )
        )
        db.commit()

        seed_tags(db)

        assert count(db, TagModel) == SEED_TAG_COUNT
        assert count(db, user_tag) == expected_interests


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
    assert [section["tag"]["name"] for section in sections] == [
        "Esportes",
        "Vida Social",
    ]

    sports = [
        (item["title"], item["participants_count"], item["event_date"] is None)
        for item in sections[0]["items"]
    ]
    # user@hangy.com already confirmed "Fut society no fim de tarde", "Pelada
    # no Parcão" and "Aniversário da Maria" and created "Corrida da Redenção"
    # and "Treino de corrida no Gasômetro": none of them is discovery.
    assert sports == [
        # PUBLIC and without user@hangy.com: the one to join directly.
        ("Corrida noturna na Orla", 2, False),
        # admin@hangy.com's PRIVATE event, with nobody in it: discoverable, but
        # the schedule stays hidden.
        ("Confraternização da equipe", 0, True),
    ]
    assert [item["title"] for item in sections[1]["items"]] == [
        "Show de rock no Opinião",
        # user@hangy.com's request is still pending.
        "Jam de rock no apê do João",
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
    ("profile_email", "expected"),
    [
        # user@hangy.com's own profile: every tab, PRIVATE events included.
        # The CANCELLED "Pelada" they had confirmed is in none of them.
        (
            "user@hangy.com",
            {
                "history": [
                    "Evento encerrado para teste de experiência",
                    "Sarau de teatro",
                ],
                "created": ["Corrida da Redenção", "Treino de corrida no Gasômetro"],
                "interests": [
                    "Show de rock no Opinião",
                    "Roda de samba na Cidade Baixa",
                ],
                "confirmed": [
                    "Fut society no fim de tarde",
                    "Pelada no Parcão",
                    "Aniversário da Maria",
                ],
            },
        ),
        # A business agenda seen by a visitor: PUBLIC only, so the PRIVATE,
        # INVITE_ONLY, DRAFT and CANCELLED events stay out.
        (
            "admin@hangy.com",
            {
                "history": [
                    "Pelada de ontem",
                    "Evento encerrado para teste de experiência",
                ],
                "created": [
                    "Fut society no fim de tarde",
                    "Pelada no Parcão",
                    "Show de rock no Opinião",
                    "Corrida noturna na Orla",
                ],
                "interests": None,
                "confirmed": None,
            },
        ),
        # "Aniversário da Maria" is PRIVATE, and what she is going to
        # ("Pelada no Parcão") is not shown to visitors.
        (
            "maria@hangy.com",
            {
                "history": ["Sarau de teatro"],
                "created": ["Roda de samba na Cidade Baixa"],
                "interests": None,
                "confirmed": None,
            },
        ),
        # Her only participation was cancelled: allowed tabs, but empty.
        (
            "ana@hangy.com",
            {"history": [], "created": [], "interests": None, "confirmed": None},
        ),
    ],
)
def test_seeded_user_events_match_the_documented_sample(
    session_factory: sessionmaker[Session],
    profile_email: str,
    expected: dict[str, list[str] | None],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        # Twice, to show the favorites are not duplicated by a restart.
        seed_everything(db)
        profile_id = db.scalar(
            select(UserModel.user_id).where(UserModel.email == profile_email)
        )

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
            f"/users/{profile_id}/events",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    titles = {
        tab: [item["title"] for item in page["items"]] if page is not None else None
        for tab, page in response.json().items()
    }
    assert titles == expected


@pytest.mark.parametrize(
    ("email", "password", "expected"),
    [
        (
            "pedro@hangy.com",
            "pedro-password",
            [
                ("Arte & Cultura", "Teatro"),
                ("Esportes", "Futebol"),
                ("Gastronomia", "Churrasco"),
                ("Gastronomia", "Doces"),
                ("Vida Social", "Sertanejo"),
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
        assert count(db, EventParticipantModel) == 23


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


@pytest.mark.parametrize(
    ("email", "password", "status_code", "expected"),
    [
        (
            "carla@hangy.com",
            "carla-password",
            200,
            {"name": "Carla Dias", "description": "Curto samba", "city": "Canoas"},
        ),
        (
            "admin@hangy.com",
            "admin-password",
            403,
            {"detail": "Not a personal profile"},
        ),
    ],
)
def test_seeded_users_cover_the_profile_update_cases(
    session_factory: sessionmaker[Session],
    email: str,
    password: str,
    status_code: int,
    expected: dict[str, str],
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
        response = client.patch(
            "/users/me/profile",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={"description": "Curto samba", "city": "Canoas"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == status_code
    assert response.json().items() >= expected.items()


def test_seed_preserves_a_profile_edited_while_testing(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        carla = db.scalar(select(UserModel).where(UserModel.email == "carla@hangy.com"))
        carla.description = "Bio editada pelo PATCH"
        carla.person_profile.city = "Canoas"
        db.commit()

        seed_everything(db)
        db.expire_all()

        assert carla.description == "Bio editada pelo PATCH"
        assert carla.person_profile.city == "Canoas"


def test_seed_events_have_a_neighborhood_a_city_and_an_approximate_point(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        events = db.scalars(select(EventModel)).all()

        assert len(events) == len(SEED_EVENTS)
        for event in events:
            assert event.location_neighborhood
            assert event.location_city == "Porto Alegre"
            assert (event.approx_latitude, event.approx_longitude) == approximate_point(
                event.event_id, event.event_latitude, event.event_longitude
            )

        # A seed that ran before these columns existed is filled in on restart,
        # without overwriting what was edited since.
        missing, customized = events[:2]
        expected_neighborhood = missing.location_neighborhood
        missing.location_neighborhood = None
        missing.location_city = None
        customized.location_neighborhood = "Bairro editado"
        db.commit()

        seed_events(db)
        db.refresh(missing)
        db.refresh(customized)

        assert missing.location_neighborhood == expected_neighborhood
        assert missing.location_city == "Porto Alegre"
        assert customized.location_neighborhood == "Bairro editado"


# The participant state each participant notification implies, and whether it
# goes to the event creator (True) or to the participant (False).
PARTICIPANT_NOTIFICATION_RULES = {
    NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST: (
        EventParticipantStatusEnum.PENDING,
        True,
    ),
    NotificationTypeEnum.EVENT_PARTICIPANT_JOINED: (
        EventParticipantStatusEnum.CONFIRMED,
        True,
    ),
    NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED: (
        EventParticipantStatusEnum.CANCELLED,
        True,
    ),
    NotificationTypeEnum.EVENT_REQUEST_APPROVED: (
        EventParticipantStatusEnum.CONFIRMED,
        False,
    ),
    NotificationTypeEnum.EVENT_REQUEST_REJECTED: (
        EventParticipantStatusEnum.REJECTED,
        False,
    ),
    NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED: (
        EventParticipantStatusEnum.REMOVED,
        False,
    ),
    NotificationTypeEnum.EVENT_STARTING_SOON: (
        EventParticipantStatusEnum.CONFIRMED,
        False,
    ),
}


def test_every_seeded_notification_has_the_state_it_describes(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        notifications = db.scalars(select(NotificationModel)).all()
        assert len(notifications) == len(SEED_NOTIFICATIONS)

        for notification in notifications:
            kind = notification.type
            if kind in (
                NotificationTypeEnum.CONNECTION_REQUEST,
                NotificationTypeEnum.CONNECTION_ACCEPTED,
            ):
                detail = db.get(
                    ConnectionNotificationModel, notification.notification_id
                )
                assert detail is not None, kind
                connection = db.get(UserConnectionModel, detail.connection_id)
                if kind == NotificationTypeEnum.CONNECTION_REQUEST:
                    assert connection.status == UserConnectionStatusEnum.PENDING
                    assert connection.receiver_id == notification.user_id
                else:
                    assert connection.status == UserConnectionStatusEnum.CONFIRMED
                    assert connection.requester_id == notification.user_id
            elif kind in PARTICIPANT_NOTIFICATION_RULES:
                detail = db.get(
                    EventParticipantNotificationModel, notification.notification_id
                )
                assert detail is not None, kind
                participant = db.get(EventParticipantModel, detail.participant_id)
                status, to_creator = PARTICIPANT_NOTIFICATION_RULES[kind]
                assert participant.status == status, kind
                event = db.get(EventModel, participant.event_id)
                recipient = (
                    event.event_creator_id if to_creator else participant.user_id
                )
                assert notification.user_id == recipient, kind
                if kind == NotificationTypeEnum.EVENT_PARTICIPANT_JOINED:
                    # Only a PUBLIC event confirms someone without approval.
                    assert event.event_privacy == EventPrivacyEnum.PUBLIC
                if kind == NotificationTypeEnum.EVENT_STARTING_SOON:
                    sent_at = notification.created_at.replace(tzinfo=UTC)
                    starts_at = event.starts_at.replace(tzinfo=UTC)
                    assert sent_at < starts_at <= sent_at + timedelta(minutes=60)
            else:
                detail = db.get(
                    EventCancelledNotificationModel, notification.notification_id
                )
                assert detail is not None, kind
                event = db.get(EventModel, detail.event_id)
                if kind == NotificationTypeEnum.EVENT_CANCELLED:
                    assert event.event_status == EventStatusEnum.CANCELLED
                else:
                    assert event.event_status == EventStatusEnum.PUBLISHED
                participant = db.scalar(
                    select(EventParticipantModel).where(
                        EventParticipantModel.event_id == event.event_id,
                        EventParticipantModel.user_id == notification.user_id,
                    )
                )
                assert participant is not None, kind
                assert participant.status == EventParticipantStatusEnum.CONFIRMED


def test_every_seeded_event_has_a_creator_and_a_tag(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

        for event in db.scalars(select(EventModel)).all():
            assert db.get(UserModel, event.event_creator_id) is not None
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(event_tag)
                    .where(event_tag.c.event_id == event.event_id)
                )
                == 1
            )
        experiences = db.scalars(select(EventExperienceModel)).all()
        for experience in experiences:
            # Only someone who went to a finished event shares an experience.
            assert experience.participant.status == EventParticipantStatusEnum.CONFIRMED
            event = db.get(EventModel, experience.participant.event_id)
            assert event.event_status == EventStatusEnum.FINISHED


def test_user_hangy_can_demo_every_flow(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        user = db.scalar(select(UserModel).where(UserModel.email == "user@hangy.com"))
        now = datetime.now(UTC)

        def status_in(title: str) -> EventParticipantStatusEnum | None:
            event = db.scalar(select(EventModel).where(EventModel.event_title == title))
            return db.scalar(
                select(EventParticipantModel.status).where(
                    EventParticipantModel.event_id == event.event_id,
                    EventParticipantModel.user_id == user.user_id,
                )
            )

        created = db.scalars(
            select(EventModel).where(EventModel.event_creator_id == user.user_id)
        ).all()
        assert {event.event_privacy for event in created} >= {
            EventPrivacyEnum.PUBLIC,
            EventPrivacyEnum.PRIVATE,
        }
        # A PUBLIC event to join and a PRIVATE one to ask to join.
        assert status_in("Corrida noturna na Orla") is None
        assert status_in("Confraternização da equipe") is None
        assert status_in("Jam de rock no apê do João") == (
            EventParticipantStatusEnum.PENDING
        )
        assert status_in("Aniversário da Maria") == EventParticipantStatusEnum.CONFIRMED
        assert status_in("Sarau de teatro") == EventParticipantStatusEnum.CONFIRMED
        # Past without a FINISHED status, still without an experience.
        finished = db.scalar(
            select(EventModel).where(
                EventModel.event_title == "Evento encerrado para teste de experiência"
            )
        )
        assert finished.starts_at.replace(tzinfo=UTC) < now
        assert status_in(finished.event_title) == EventParticipantStatusEnum.CONFIRMED

        admin = db.scalar(select(UserModel).where(UserModel.email == "admin@hangy.com"))
        assert db.get(UserFollowModel, (user.user_id, admin.user_id)) is not None
        assert (
            db.scalar(
                select(func.count())
                .select_from(UserBlockModel)
                .where(UserBlockModel.blocker_id == user.user_id)
            )
            == 1
        )
        statuses = db.scalars(
            select(UserConnectionModel.status).where(
                (UserConnectionModel.requester_id == user.user_id)
                | (UserConnectionModel.receiver_id == user.user_id)
            )
        ).all()
        assert set(statuses) == {
            UserConnectionStatusEnum.PENDING,
            UserConnectionStatusEnum.CONFIRMED,
        }


def test_seed_restores_connections_follows_blocks_and_photos(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        request = db.scalar(
            select(UserConnectionModel).where(
                UserConnectionModel.status == UserConnectionStatusEnum.PENDING
            )
        )
        request.status = UserConnectionStatusEnum.CONFIRMED
        db.execute(delete(UserFollowModel))
        db.execute(delete(UserBlockModel))
        photo = db.scalars(select(ExperienceImagesModel)).first()
        photo.deleted_at = datetime.now(UTC)
        db.commit()

        seed_everything(db)
        db.refresh(request)
        db.refresh(photo)

        assert request.status == UserConnectionStatusEnum.PENDING
        assert count(db, UserFollowModel) == sum(map(len, SEED_FOLLOWS.values()))
        assert count(db, UserBlockModel) == len(SEED_BLOCKS)
        assert photo.deleted_at is None
        assert count(db, ExperienceImagesModel) == sum(
            len(experience.photo_urls) for experience in SEED_EXPERIENCES
        )


def test_seeded_photos_show_up_for_user_hangy(
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
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        photos = client.get("/users/me/photos", headers=headers)
        blocked = client.get("/users/me/blocked", headers=headers)
    app.dependency_overrides.clear()

    assert photos.status_code == 200
    assert len(photos.json()["items"]) == 2
    assert blocked.status_code == 200
    assert blocked.json()
