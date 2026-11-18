from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    AuditActionEnum,
    AuditTargetTypeEnum,
    EventModerationStatusEnum,
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
    UserConnectionStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services.event_location import approximate_point
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    AuditLogModel,
    ConnectionNotificationModel,
    EventCancelledNotificationModel,
    EventExperienceModel,
    EventInviteLinkModel,
    EventModel,
    EventParticipantModel,
    EventParticipantNotificationModel,
    ExperienceImagesModel,
    NotificationModel,
    ReportModel,
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
    SEED_REPORTS,
    SEED_TAGS,
    SEED_USERS,
    SeedReport,
    seed_event_id,
    seed_events,
    seed_experiences,
    seed_moderation,
    seed_notification_id,
    seed_notifications,
    seed_report_id,
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
    seed_moderation(db)


def count(db: Session, entity: object) -> int:
    return db.scalar(select(func.count()).select_from(entity))


def count_where(db: Session, entity: object, condition: object) -> int:
    return db.scalar(select(func.count()).select_from(entity).where(condition))


def seed_events_created_by(db: Session, creator: UserModel, title: str) -> UUID:
    starts_at = datetime.now(UTC) + timedelta(days=2)
    event = EventModel(
        event_creator_id=creator.user_id,
        event_title=title,
        location_name="Parcão",
        location_neighborhood="Moinhos de Vento",
        location_city="Porto Alegre",
        event_latitude=-30.03,
        event_longitude=-51.2,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        event_status=EventStatusEnum.PUBLISHED,
        event_privacy=EventPrivacyEnum.PUBLIC,
    )
    db.add(event)
    db.flush()
    return event.event_id


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
        assert count(db, EventParticipantModel) == 24
        assert count(db, NotificationModel) == len(SEED_NOTIFICATIONS)
        assert count(db, UserFollowModel) == sum(map(len, SEED_FOLLOWS.values()))
        assert count(db, UserBlockModel) == len(SEED_BLOCKS)
        assert count(db, EventExperienceModel) == len(SEED_EXPERIENCES)
        assert count(db, ExperienceImagesModel) == sum(
            len(experience.photo_urls) for experience in SEED_EXPERIENCES
        )
        assert count(db, ReportModel) == len(SEED_REPORTS)
        assert count(db, AuditLogModel) == sum(
            report.resolution is not None for report in SEED_REPORTS
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
        # estabelecimento@hangy.com's PRIVATE event, with nobody in it:
        # discoverable, but the schedule stays hidden.
        ("Confraternização da equipe", 0, True),
    ]
    assert [item["title"] for item in sections[1]["items"]] == [
        "Show de rock no Opinião",
        # user@hangy.com's request is still pending.
        "Jam de rock no apê do João",
    ]


def test_seed_makes_admin_hangy_an_admin_without_business_data(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        admin = db.scalar(select(UserModel).where(UserModel.email == "admin@hangy.com"))
        assert admin.role == UserRoleEnum.ADMIN
        assert admin.business_profile is not None
        assert (
            count_where(db, EventModel, EventModel.event_creator_id == admin.user_id)
            == 0
        )
        assert (
            count_where(
                db,
                UserFollowModel,
                UserFollowModel.followed_business_id == admin.user_id,
            )
            == 0
        )
        others = db.scalars(
            select(UserModel.role).where(UserModel.email != "admin@hangy.com")
        ).all()
        assert set(others) == {UserRoleEnum.USER}

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": "admin@hangy.com", "password": "admin-password"},
        )
    app.dependency_overrides.clear()

    assert login.status_code == 200
    assert login.json()["user"]["role"] == "ADMIN"


def test_seed_hands_admin_hangy_business_data_over_to_the_business(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        users = {user.email: user for user in db.scalars(select(UserModel))}
        admin = users["admin@hangy.com"]
        business = users["estabelecimento@hangy.com"]
        # The state an older seed left: admin@hangy.com owned the demo events,
        # their invite links and the followers, was a USER, and a tester
        # created one more event with it.
        admin.role = UserRoleEnum.USER
        db.execute(
            update(EventModel)
            .where(EventModel.event_creator_id == business.user_id)
            .values(event_creator_id=admin.user_id)
        )
        db.execute(
            update(EventInviteLinkModel)
            .where(EventInviteLinkModel.created_by == business.user_id)
            .values(created_by=admin.user_id)
        )
        db.execute(delete(UserFollowModel))
        db.add_all(
            [
                UserFollowModel(
                    follower_id=users[email].user_id,
                    followed_business_id=admin.user_id,
                )
                for email in ("user@hangy.com", "maria@hangy.com", "joao@hangy.com")
            ]
        )
        # Already follows both: must not end up with a duplicate follow.
        db.add(
            UserFollowModel(
                follower_id=users["maria@hangy.com"].user_id,
                followed_business_id=business.user_id,
            )
        )
        created_while_testing = seed_events_created_by(db, admin, "Evento do teste")
        db.commit()
        event_ids = set(db.scalars(select(EventModel.event_id)))

        seed_everything(db)
        db.expire_all()

        assert admin.role == UserRoleEnum.ADMIN
        assert set(db.scalars(select(EventModel.event_id))) == event_ids
        assert (
            set(
                db.scalars(
                    select(EventModel.event_id).where(
                        EventModel.event_creator_id == admin.user_id
                    )
                )
            )
            == set()
        )
        assert db.get(EventModel, created_while_testing).event_creator_id == (
            business.user_id
        )
        assert (
            count_where(
                db,
                EventInviteLinkModel,
                EventInviteLinkModel.created_by == admin.user_id,
            )
            == 0
        )
        followers = db.scalars(
            select(UserFollowModel.follower_id).where(
                UserFollowModel.followed_business_id == business.user_id
            )
        ).all()
        assert sorted(followers) == sorted(
            users[email].user_id
            for email in ("user@hangy.com", "maria@hangy.com", "joao@hangy.com")
        )
        assert count(db, UserFollowModel) == 3


def test_seed_restores_the_admin_role_removed_while_testing(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        admin = db.scalar(select(UserModel).where(UserModel.email == "admin@hangy.com"))
        admin.role = UserRoleEnum.USER
        db.commit()

        seed_everything(db)
        db.refresh(admin)

        assert admin.role == UserRoleEnum.ADMIN


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
            json={
                "email": "estabelecimento@hangy.com",
                "password": "estabelecimento-password",
            },
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
        # INVITE_ONLY, DRAFT, CANCELLED and removed events stay out.
        (
            "estabelecimento@hangy.com",
            {
                "history": [
                    "Pelada de ontem",
                    "Evento encerrado para teste de experiência",
                ],
                "created": [
                    "Fut society no fim de tarde",
                    "Pelada no Parcão",
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
    # Every type but EVENT_PARTICIPANT_CANCELLED, which the app never sends.
    assert {item["type"] for item in items} == {
        notification_type.value
        for notification_type in NotificationTypeEnum
        if notification_type is not NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED
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
    assert payloads["EVENT_REMOVED"]["event_title"] == "Festa open bar no Parcão"


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
        NotificationTypeEnum.EVENT_PARTICIPANT_REMOVED: (
            EventParticipantStatusEnum.REMOVED
        ),
    }
    # Who receives it: the event's creator, or the participant themself.
    recipient_is_creator = {
        NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
        NotificationTypeEnum.EVENT_PARTICIPANT_JOINED,
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
            elif kind in (
                NotificationTypeEnum.EVENT_UPDATED,
                NotificationTypeEnum.EVENT_REMOVED,
            ):
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
        assert count(db, EventParticipantModel) == 24


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
            "estabelecimento@hangy.com",
            "estabelecimento-password",
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
                if kind in (
                    NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST,
                    NotificationTypeEnum.EVENT_REQUEST_APPROVED,
                    NotificationTypeEnum.EVENT_REQUEST_REJECTED,
                ):
                    # Requests only exist for PRIVATE events.
                    assert event.event_privacy == EventPrivacyEnum.PRIVATE, kind
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
                participant = db.scalar(
                    select(EventParticipantModel).where(
                        EventParticipantModel.event_id == event.event_id,
                        EventParticipantModel.user_id == notification.user_id,
                    )
                )
                if kind == NotificationTypeEnum.EVENT_REMOVED:
                    # A takedown tells the organizer and cancels everyone
                    # else's participation, at the moment it is notified.
                    assert event.moderation_status == EventModerationStatusEnum.REMOVED
                    assert event.deleted_at is not None
                    assert event.removed_at.replace(tzinfo=UTC) == (
                        notification.created_at.replace(tzinfo=UTC)
                    )
                    if notification.user_id != event.event_creator_id:
                        assert participant.status == (
                            EventParticipantStatusEnum.CANCELLED
                        )
                    continue
                assert event.moderation_status == EventModerationStatusEnum.ACTIVE
                if kind == NotificationTypeEnum.EVENT_CANCELLED:
                    assert event.event_status == EventStatusEnum.CANCELLED
                else:
                    assert event.event_status == EventStatusEnum.PUBLISHED
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

        business = db.scalar(
            select(UserModel).where(UserModel.email == "estabelecimento@hangy.com")
        )
        assert db.get(UserFollowModel, (user.user_id, business.user_id)) is not None
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


def test_every_seeded_event_and_connection_predates_what_refers_to_it(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)

        def as_utc(value: datetime) -> datetime:
            return value.replace(tzinfo=UTC)

        oldest_notification = min(
            as_utc(n.created_at) for n in db.scalars(select(NotificationModel))
        )
        oldest_report = min(
            as_utc(r.created_at) for r in db.scalars(select(ReportModel))
        )
        for event in db.scalars(select(EventModel)):
            assert as_utc(event.created_at) < oldest_notification
            assert as_utc(event.created_at) < oldest_report
        for connection in db.scalars(select(UserConnectionModel)):
            assert as_utc(connection.created_at) < oldest_notification


def test_seed_retires_the_participant_cancelled_notification(
    session_factory: sessionmaker[Session],
) -> None:
    retired_id = seed_notification_id("user@hangy.com", "participant-cancelled")
    with session_factory() as db:
        seed_everything(db)
        # What an older seed left behind.
        user = db.scalar(select(UserModel).where(UserModel.email == "user@hangy.com"))
        db.add(
            NotificationModel(
                notification_id=retired_id,
                user_id=user.user_id,
                type=NotificationTypeEnum.EVENT_PARTICIPANT_CANCELLED,
            )
        )
        ana_participation = db.scalar(
            select(EventParticipantModel.participant_id).where(
                EventParticipantModel.event_id
                == seed_event_id("user@hangy.com", "Corrida da Redenção"),
                EventParticipantModel.status == EventParticipantStatusEnum.CANCELLED,
            )
        )
        db.add(
            EventParticipantNotificationModel(
                notification_id=retired_id, participant_id=ana_participation
            )
        )
        db.commit()

        seed_everything(db)

        assert db.get(NotificationModel, retired_id) is None
        assert db.get(EventParticipantNotificationModel, retired_id) is None
        assert count(db, NotificationModel) == len(SEED_NOTIFICATIONS)


def test_seed_moderation_matches_the_reports_behind_it(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        seed_everything(db)
        now = datetime.now(UTC)
        users = {user.email: user for user in db.scalars(select(UserModel))}
        admin = users["admin@hangy.com"]

        bruno, camila = users["bruno@hangy.com"], users["camila@hangy.com"]
        assert bruno.banned_at is not None
        assert bruno.suspended_until is None
        assert camila.banned_at is None
        assert camila.suspended_until.replace(tzinfo=UTC) > now
        # Nobody else is moderated.
        assert {
            email
            for email, user in users.items()
            if user.banned_at is not None or user.suspended_until is not None
        } == {"bruno@hangy.com", "camila@hangy.com"}

        for seed in SEED_REPORTS:
            report = db.get(ReportModel, seed_report_id(seed.key))
            if seed.resolution is None:
                assert report.status == ReportStatusEnum.PENDING
                assert report.resolved_at is None
                assert (
                    db.scalar(
                        select(AuditLogModel).where(
                            AuditLogModel.target_id
                            == (report.reported_user_id or report.reported_event_id)
                        )
                    )
                    is None
                )
                continue
            assert report.status == ReportStatusEnum.RESOLVED
            assert report.resolved_by_id == admin.user_id
            resolved_at = report.resolved_at.replace(tzinfo=UTC)
            assert report.created_at.replace(tzinfo=UTC) < resolved_at
            audit = db.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.target_id
                    == (report.reported_user_id or report.reported_event_id)
                )
            )
            assert audit.actor_id == admin.user_id
            assert audit.created_at.replace(tzinfo=UTC) == resolved_at
            if seed.resolution is ReportResolutionActionEnum.BANNED:
                assert audit.action == AuditActionEnum.USER_BANNED
                assert bruno.banned_at.replace(tzinfo=UTC) == resolved_at
            elif seed.resolution is ReportResolutionActionEnum.SUSPENDED:
                assert audit.action == AuditActionEnum.USER_SUSPENDED
                assert camila.suspended_until.replace(tzinfo=UTC) == (
                    resolved_at + timedelta(days=seed.suspension_days)
                )
            else:
                assert audit.action == AuditActionEnum.EVENT_REMOVED
                assert audit.target_type == AuditTargetTypeEnum.EVENT
                event = db.get(EventModel, report.reported_event_id)
                assert event.moderation_status == EventModerationStatusEnum.REMOVED
                assert event.removed_at.replace(tzinfo=UTC) == resolved_at
            if audit.target_type == AuditTargetTypeEnum.USER:
                assert audit.extra_metadata == {"report_id": str(report.report_id)}


def test_seed_restores_moderation_and_event_state_changed_while_testing(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        users = {user.email: user for user in db.scalars(select(UserModel))}
        users["bruno@hangy.com"].banned_at = None
        users["camila@hangy.com"].suspended_until = None
        cancelled = db.get(
            EventModel, seed_event_id("estabelecimento@hangy.com", "Pelada no Parcão")
        )
        cancelled.event_status = EventStatusEnum.CANCELLED
        cancelled.event_privacy = EventPrivacyEnum.PRIVATE
        removed = db.get(
            EventModel, seed_event_id("maria@hangy.com", "Aniversário da Maria")
        )
        removed.moderation_status = EventModerationStatusEnum.REMOVED
        removed.deleted_at = datetime.now(UTC)
        db.commit()

        seed_everything(db)
        db.expire_all()

        assert users["bruno@hangy.com"].banned_at is not None
        assert users["camila@hangy.com"].suspended_until is not None
        assert cancelled.event_status == EventStatusEnum.PUBLISHED
        assert cancelled.event_privacy == EventPrivacyEnum.PUBLIC
        assert removed.moderation_status == EventModerationStatusEnum.ACTIVE
        assert removed.deleted_at is None
        assert removed.removed_at is None


def test_seed_pending_reports_cover_a_person_a_business_and_an_event(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        pending = db.scalars(
            select(ReportModel).where(ReportModel.status == ReportStatusEnum.PENDING)
        ).all()

        targets = {
            report.reported_user.user_type
            if report.reported_user is not None
            else "EVENT"
            for report in pending
        }
        assert targets == {UserTypeEnum.PERSONAL, UserTypeEnum.BUSINESS, "EVENT"}
        assert all(report.resolved_at is None for report in pending)


@pytest.mark.parametrize(
    "seed",
    [report for report in SEED_REPORTS if report.resolution is None],
    ids=lambda report: report.key,
)
def test_seeded_pending_report_is_one_its_author_could_open(
    session_factory: sessionmaker[Session], seed: SeedReport
) -> None:
    """GET /reports/reasons accepts the target and sees the open report."""
    with session_factory() as db:
        seed_everything(db)
        report = db.get(ReportModel, seed_report_id(seed.key))
        target, target_id = (
            ("USER", report.reported_user_id)
            if report.reported_user_id is not None
            else ("EVENT", report.reported_event_id)
        )
    password = next(
        user.password for user in SEED_USERS if user.email == seed.creator_email
    )

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"email": seed.creator_email, "password": password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        reasons = client.get(
            "/reports/reasons",
            params={"target": target, "target_id": str(target_id)},
            headers=headers,
        )
    app.dependency_overrides.clear()

    assert reasons.status_code == 200
    reason = next(r for r in reasons.json() if r["code"] == seed.report_type)
    assert reason["available"] is False
    assert reason["unavailable_reason"] == "ALREADY_REPORTED"


@pytest.mark.parametrize(
    ("email", "password"),
    [("bruno@hangy.com", "bruno-password"), ("camila@hangy.com", "camila-password")],
)
def test_seeded_moderated_accounts_cannot_log_in(
    session_factory: sessionmaker[Session], email: str, password: str
) -> None:
    with session_factory() as db:
        seed_everything(db)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post("/auth/login", json={"email": email, "password": password})
    app.dependency_overrides.clear()

    assert login.status_code == 403
    assert login.json() == {"detail": "Account is banned or suspended"}


def test_seeded_removed_event_is_hidden_from_the_feed_and_profiles(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as db:
        seed_everything(db)
        removed_id = seed_event_id(
            "estabelecimento@hangy.com", "Festa open bar no Parcão"
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
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        details = client.get(f"/events/{removed_id}", headers=headers)
    app.dependency_overrides.clear()

    assert details.status_code == 404
