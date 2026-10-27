from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.entities import AdminUserRecord
from app.domain.enums import (
    EventPrivacyEnum,
    EventStatusEnum,
    ModerationStatusEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services import AdminUsersService, derive_moderation_status
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel
from app.main import app

AdminClient = tuple[TestClient, sessionmaker[Session]]

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
# The moderation columns arrive with task 249; until then everyone is ACTIVE.
HAS_MODERATION_COLUMNS = hasattr(UserModel, "banned_at") and hasattr(
    UserModel, "suspended_until"
)


@pytest.fixture
def admin_client() -> Iterator[AdminClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def override_get_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def header_for(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def add_user(
    db: Session,
    *,
    name: str,
    created_at: datetime,
    email: str | None = None,
    role: UserRoleEnum = UserRoleEnum.USER,
    user_type: UserTypeEnum = UserTypeEnum.PERSONAL,
    deleted_at: datetime | None = None,
    user_id: UUID | None = None,
    **extra: object,
) -> UUID:
    user_id = user_id or uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=user_type,
            role=role,
            email=email or f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
            created_at=created_at,
            deleted_at=deleted_at,
            **extra,
        )
    )
    db.commit()
    return user_id


def add_event(
    db: Session, creator_id: UUID, *, deleted_at: datetime | None = None
) -> UUID:
    event_id = uuid4()
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=creator_id,
            event_title="Evento",
            event_latitude=-30.03,
            event_longitude=-51.23,
            starts_at=NOW + timedelta(days=1),
            ends_at=NOW + timedelta(days=1, hours=3),
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=EventPrivacyEnum.PUBLIC,
            deleted_at=deleted_at,
        )
    )
    db.commit()
    return event_id


def add_report(
    db: Session,
    creator_id: UUID,
    *,
    reported_user_id: UUID | None = None,
    reported_event_id: UUID | None = None,
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
    deleted_at: datetime | None = None,
) -> None:
    db.add(
        ReportModel(
            report_creator_id=creator_id,
            reported_user_id=reported_user_id,
            reported_event_id=reported_event_id,
            report_type=ReportTypeEnum.HARASSMENT,
            description="Mensagens ofensivas",
            status=status,
            deleted_at=deleted_at,
        )
    )
    db.commit()


def add_admin(session_factory: sessionmaker[Session]) -> UUID:
    with session_factory() as db:
        return add_user(
            db,
            name="Admin",
            email="admin@hangy.com",
            role=UserRoleEnum.ADMIN,
            created_at=NOW - timedelta(days=365),
        )


def names(response) -> list[str]:
    return [item["name"] for item in response.json()["items"]]


def test_admin_lists_users_with_counts_and_derived_status(
    admin_client: AdminClient,
) -> None:
    client, session_factory = admin_client
    admin_id = add_admin(session_factory)
    with session_factory() as db:
        marina = add_user(db, name="Marina Schmitt", created_at=NOW - timedelta(days=3))
        bar = add_user(
            db,
            name="Bar do Zé",
            user_type=UserTypeEnum.BUSINESS,
            created_at=NOW - timedelta(days=2),
        )
        rafael = add_user(db, name="Rafael Antunes", created_at=NOW - timedelta(days=1))
        add_user(
            db,
            name="Conta Excluída",
            created_at=NOW - timedelta(hours=1),
            deleted_at=NOW,
        )

        rafael_event = add_event(db, rafael)
        add_event(db, rafael)
        add_event(db, rafael, deleted_at=NOW)
        bar_event = add_event(db, bar)

        # Against Rafael: his profile (any status), and one of his events.
        add_report(db, marina, reported_user_id=rafael)
        add_report(
            db, marina, reported_user_id=rafael, status=ReportStatusEnum.RESOLVED
        )
        add_report(db, marina, reported_event_id=rafael_event)
        # Archived reports do not count.
        add_report(db, marina, reported_user_id=rafael, deleted_at=NOW)
        # Against the business's event, not Rafael's.
        add_report(db, rafael, reported_event_id=bar_event)

    response = client.get("/admin/users", headers=header_for(admin_id))

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "user_id": str(rafael),
                "name": "Rafael Antunes",
                "moderation_status": "ACTIVE",
                "suspended_until": None,
                "event_count": 2,
                "report_count": 3,
            },
            {
                "user_id": str(bar),
                "name": "Bar do Zé",
                "moderation_status": "ACTIVE",
                "suspended_until": None,
                "event_count": 1,
                "report_count": 1,
            },
            {
                "user_id": str(marina),
                "name": "Marina Schmitt",
                "moderation_status": "ACTIVE",
                "suspended_until": None,
                "event_count": 0,
                "report_count": 0,
            },
            {
                "user_id": str(admin_id),
                "name": "Admin",
                "moderation_status": "ACTIVE",
                "suspended_until": None,
                "event_count": 0,
                "report_count": 0,
            },
        ],
        "next_cursor": None,
    }


@pytest.mark.skipif(
    HAS_MODERATION_COLUMNS, reason="task 249 merged: covered by the status tests"
)
def test_without_moderation_columns_everyone_is_active(
    admin_client: AdminClient,
) -> None:
    client, session_factory = admin_client
    admin_id = add_admin(session_factory)
    with session_factory() as db:
        add_user(db, name="Marina", created_at=NOW - timedelta(days=1))

    active = client.get("/admin/users?status=ACTIVE", headers=header_for(admin_id))
    suspended = client.get(
        "/admin/users?status=SUSPENDED", headers=header_for(admin_id)
    )
    banned = client.get("/admin/users?status=BANNED", headers=header_for(admin_id))

    assert names(active) == ["Marina", "Admin"]
    assert names(suspended) == []
    assert names(banned) == []


@pytest.mark.skipif(
    not HAS_MODERATION_COLUMNS, reason="needs user.banned_at/suspended_until (249)"
)
def test_status_filter_and_derivation_with_moderation_columns(
    admin_client: AdminClient,
) -> None:
    client, session_factory = admin_client
    admin_id = add_admin(session_factory)
    now = datetime.now(UTC)
    suspended_until = now + timedelta(days=5)
    with session_factory() as db:
        add_user(db, name="Ativo", created_at=now - timedelta(days=4))
        suspended = add_user(
            db,
            name="Suspenso",
            created_at=now - timedelta(days=3),
            suspended_until=suspended_until,
        )
        add_user(
            db,
            name="Suspensão vencida",
            created_at=now - timedelta(days=2),
            suspended_until=now - timedelta(minutes=1),
        )
        add_user(
            db,
            name="Banido",
            created_at=now - timedelta(days=1),
            banned_at=now - timedelta(days=1),
            suspended_until=suspended_until,
        )
    headers = header_for(admin_id)

    everyone = client.get("/admin/users", headers=headers).json()["items"]
    statuses = {item["name"]: item["moderation_status"] for item in everyone}
    assert statuses == {
        "Banido": "BANNED",
        "Suspensão vencida": "ACTIVE",
        "Suspenso": "SUSPENDED",
        "Ativo": "ACTIVE",
        "Admin": "ACTIVE",
    }
    suspended_item = next(i for i in everyone if i["user_id"] == str(suspended))
    assert datetime.fromisoformat(suspended_item["suspended_until"]) == (
        suspended_until
    )

    assert names(client.get("/admin/users?status=SUSPENDED", headers=headers)) == [
        "Suspenso"
    ]
    assert names(client.get("/admin/users?status=BANNED", headers=headers)) == [
        "Banido"
    ]
    assert names(client.get("/admin/users?status=ACTIVE", headers=headers)) == [
        "Suspensão vencida",
        "Ativo",
        "Admin",
    ]


@pytest.mark.parametrize(
    ("banned_at", "suspended_until", "expected"),
    [
        (None, None, ModerationStatusEnum.ACTIVE),
        (None, NOW + timedelta(seconds=1), ModerationStatusEnum.SUSPENDED),
        # The suspension ends exactly at suspended_until.
        (None, NOW, ModerationStatusEnum.ACTIVE),
        (None, NOW - timedelta(days=1), ModerationStatusEnum.ACTIVE),
        (NOW - timedelta(days=1), None, ModerationStatusEnum.BANNED),
        (NOW, NOW + timedelta(days=1), ModerationStatusEnum.BANNED),
        # SQLite returns naive datetimes; they are read as UTC.
        (
            None,
            (NOW + timedelta(hours=1)).replace(tzinfo=None),
            ModerationStatusEnum.SUSPENDED,
        ),
    ],
)
def test_derive_moderation_status(
    banned_at: datetime | None,
    suspended_until: datetime | None,
    expected: ModerationStatusEnum,
) -> None:
    assert derive_moderation_status(banned_at, suspended_until, NOW) == expected


class FakeAdminUsersRepository:
    def __init__(self, rows: list[AdminUserRecord]) -> None:
        self.rows = rows
        self.calls: list[tuple] = []

    def list_users(self, now, status, search, limit, after):
        self.calls.append((now, status, search, limit, after))
        return self.rows[:limit]


def record(**overrides: object) -> AdminUserRecord:
    values: dict[str, object] = {
        "user_id": uuid4(),
        "name": "Pessoa",
        "created_at": NOW - timedelta(days=1),
        "banned_at": None,
        "suspended_until": None,
        "event_count": 0,
        "report_count": 0,
    }
    values.update(overrides)
    return AdminUserRecord(**values)  # type: ignore[arg-type]


def test_service_shows_suspended_until_only_for_a_running_suspension() -> None:
    until = NOW + timedelta(days=2)
    repository = FakeAdminUsersRepository(
        [
            record(name="Suspenso", suspended_until=until),
            record(name="Vencida", suspended_until=NOW - timedelta(days=2)),
            record(name="Banido", banned_at=NOW, suspended_until=until),
        ]
    )

    page = AdminUsersService(repository).get_users(now=NOW)

    assert [(i.name, i.moderation_status, i.suspended_until) for i in page.items] == [
        ("Suspenso", ModerationStatusEnum.SUSPENDED, until),
        ("Vencida", ModerationStatusEnum.ACTIVE, None),
        ("Banido", ModerationStatusEnum.BANNED, None),
    ]


def test_service_passes_filters_and_blank_search_becomes_none() -> None:
    repository = FakeAdminUsersRepository([])
    service = AdminUsersService(repository)

    service.get_users(status=ModerationStatusEnum.BANNED, search="   ", now=NOW)
    service.get_users(search="  ana ", now=NOW)

    assert repository.calls == [
        (NOW, ModerationStatusEnum.BANNED, None, 21, None),
        (NOW, None, "ana", 21, None),
    ]


def test_search_matches_name_or_email_case_insensitively(
    admin_client: AdminClient,
) -> None:
    client, session_factory = admin_client
    admin_id = add_admin(session_factory)
    with session_factory() as db:
        add_user(
            db,
            name="Marina Schmitt",
            email="marina@hangy.com",
            created_at=NOW - timedelta(days=3),
        )
        add_user(
            db,
            name="Rafael Antunes",
            email="rafa_contato@exemplo.com",
            created_at=NOW - timedelta(days=2),
        )
        add_user(
            db,
            name="Ana_Paula",
            email="ana@hangy.com",
            created_at=NOW - timedelta(days=1),
        )
    headers = header_for(admin_id)

    def search(term: str) -> list[str]:
        response = client.get("/admin/users", params={"search": term}, headers=headers)
        assert response.status_code == 200
        return names(response)

    assert search("SCHMITT") == ["Marina Schmitt"]
    assert search("exemplo.com") == ["Rafael Antunes"]
    assert search("hangy.com") == ["Ana_Paula", "Marina Schmitt", "Admin"]
    # LIKE wildcards in the input are matched literally.
    assert search("_") == ["Ana_Paula", "Rafael Antunes"]
    assert search("%") == []
    assert search("ninguém") == []


def test_search_and_status_combine(admin_client: AdminClient) -> None:
    client, session_factory = admin_client
    admin_id = add_admin(session_factory)
    with session_factory() as db:
        add_user(db, name="Marina", created_at=NOW - timedelta(days=1))
        add_user(db, name="Rafael", created_at=NOW - timedelta(days=2))

    response = client.get(
        "/admin/users",
        params={"status": "ACTIVE", "search": "mar"},
        headers=header_for(admin_id),
    )

    assert response.status_code == 200
    assert names(response) == ["Marina"]


def test_pagination_walks_every_user_once_by_newest_first(
    admin_client: AdminClient,
) -> None:
    client, session_factory = admin_client
    admin_id = add_admin(session_factory)
    tie = NOW - timedelta(days=1)
    with session_factory() as db:
        # Same created_at: the user_id tiebreak must keep the order stable.
        add_user(db, name="Tie A", created_at=tie, user_id=UUID(int=1))
        add_user(db, name="Tie B", created_at=tie, user_id=UUID(int=2))
        add_user(db, name="Mais nova", created_at=NOW)
    headers = header_for(admin_id)

    first = client.get("/admin/users?limit=2", headers=headers)
    assert first.status_code == 200
    assert names(first) == ["Mais nova", "Tie B"]
    cursor = first.json()["next_cursor"]
    assert cursor is not None

    second = client.get(
        "/admin/users", params={"limit": 2, "cursor": cursor}, headers=headers
    )
    assert second.status_code == 200
    assert names(second) == ["Tie A", "Admin"]
    assert second.json()["next_cursor"] is None


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "limit=abc", "cursor=not-a-cursor"],
)
def test_invalid_pagination_returns_400(admin_client: AdminClient, query: str) -> None:
    client, session_factory = admin_client
    admin_id = add_admin(session_factory)

    response = client.get(f"/admin/users?{query}", headers=header_for(admin_id))

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


@pytest.mark.parametrize("query", ["status=DELETED", f"search={'a' * 101}"])
def test_invalid_filters_return_422(admin_client: AdminClient, query: str) -> None:
    client, session_factory = admin_client
    admin_id = add_admin(session_factory)

    response = client.get(f"/admin/users?{query}", headers=header_for(admin_id))

    assert response.status_code == 422


def test_non_admin_receives_403(admin_client: AdminClient) -> None:
    client, session_factory = admin_client
    with session_factory() as db:
        user_id = add_user(db, name="Comum", created_at=NOW)

    response = client.get("/admin/users", headers=header_for(user_id))

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_missing_token_receives_401(admin_client: AdminClient) -> None:
    client, _ = admin_client

    response = client.get("/admin/users")

    assert response.status_code == 401
