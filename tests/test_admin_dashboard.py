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
from app.domain.enums import (
    EventPrivacyEnum,
    EventStatusEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel
from app.main import app

DashboardClient = tuple[TestClient, sessionmaker[Session]]


@pytest.fixture
def dashboard_client() -> Iterator[DashboardClient]:
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
    name: str = "Pessoa",
    role: UserRoleEnum = UserRoleEnum.USER,
    user_type: UserTypeEnum = UserTypeEnum.PERSONAL,
    created_at: datetime | None = None,
    deleted_at: datetime | None = None,
    **extra: object,
) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=user_type,
            role=role,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
            created_at=created_at or datetime.now(UTC),
            deleted_at=deleted_at,
            **extra,
        )
    )
    db.commit()
    return user_id


def add_report(
    db: Session,
    creator_id: UUID,
    *,
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
    opened_at: datetime | None = None,
    reported_user_id: UUID | None = None,
    reported_event_id: UUID | None = None,
    report_type: ReportTypeEnum = ReportTypeEnum.HARASSMENT,
    description: str = "Mensagens ofensivas",
    deleted_at: datetime | None = None,
    report_id: UUID | None = None,
) -> UUID:
    report_id = report_id or uuid4()
    db.add(
        ReportModel(
            report_id=report_id,
            report_creator_id=creator_id,
            reported_user_id=reported_user_id,
            reported_event_id=reported_event_id,
            report_type=report_type,
            description=description,
            status=status,
            updated_at=opened_at or datetime.now(UTC),
            deleted_at=deleted_at,
        )
    )
    db.commit()
    return report_id


def add_event(db: Session, creator_id: UUID, title: str) -> UUID:
    event_id = uuid4()
    now = datetime.now(UTC)
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=creator_id,
            event_title=title,
            event_latitude=-30.03,
            event_longitude=-51.23,
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=1, hours=3),
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=EventPrivacyEnum.PUBLIC,
        )
    )
    db.commit()
    return event_id


def make_admin(session_factory: sessionmaker[Session]) -> UUID:
    with session_factory() as db:
        return add_user(db, name="Admin", role=UserRoleEnum.ADMIN)


def test_admin_receives_the_dashboard_metrics(
    dashboard_client: DashboardClient,
) -> None:
    client, session_factory = dashboard_client
    now = datetime.now(UTC)
    admin_id = make_admin(session_factory)
    with session_factory() as db:
        # Admin (just now) + two accounts: one new this week, one old.
        reporter = add_user(db, created_at=now - timedelta(days=2))
        add_user(db, created_at=now - timedelta(days=30))
        add_user(db, created_at=now - timedelta(days=1), deleted_at=now)
        target = add_user(db, name="Lucas Ferreira")

        add_report(db, reporter, reported_user_id=target, opened_at=now)
        add_report(
            db, reporter, reported_user_id=target, opened_at=now - timedelta(hours=3)
        )
        add_report(
            db, reporter, reported_user_id=target, opened_at=now - timedelta(days=3)
        )
        add_report(
            db,
            reporter,
            reported_user_id=target,
            status=ReportStatusEnum.REVIEWED,
        )
        add_report(
            db,
            reporter,
            reported_user_id=target,
            status=ReportStatusEnum.RESOLVED,
        )
        add_report(
            db,
            reporter,
            reported_user_id=target,
            status=ReportStatusEnum.REJECTED,
        )
        add_report(db, reporter, reported_user_id=target, deleted_at=now)

    response = client.get("/admin/dashboard", headers=header_for(admin_id))

    assert response.status_code == 200
    body = response.json()
    assert body["reports_open"] == 3
    assert body["reports_open_last_24h"] == 2
    assert body["reports_in_review"] == 1
    assert body["reports_in_review_moderators"] == 0
    # admin + reporter + the 30-day-old account + target (deleted one excluded)
    assert body["active_users"] == 4
    # admin + reporter + target joined in the last 7 days
    assert body["active_users_new_this_week"] == 3
    assert body["suspended_accounts"] == 0
    assert body["suspended_accounts_expiring_today"] == 0
    assert len(body["recent_reports"]) == 4  # 3 pending + 1 reviewed


@pytest.mark.skipif(
    not hasattr(UserModel, "suspended_until"),
    reason="user.suspended_until is created by task 249",
)
def test_suspended_accounts_are_counted_and_leave_active_users(
    dashboard_client: DashboardClient,
) -> None:
    client, session_factory = dashboard_client
    now = datetime.now(UTC)
    admin_id = make_admin(session_factory)
    with session_factory() as db:
        add_user(db, suspended_until=now + timedelta(minutes=1))
        add_user(db, suspended_until=now + timedelta(days=5))
        add_user(db, suspended_until=now - timedelta(days=1))  # already over

    response = client.get("/admin/dashboard", headers=header_for(admin_id))

    body = response.json()
    assert body["suspended_accounts"] == 2
    assert body["suspended_accounts_expiring_today"] <= 2
    assert body["active_users"] == 2  # admin + the expired suspension


def test_regular_user_gets_403(dashboard_client: DashboardClient) -> None:
    client, session_factory = dashboard_client
    with session_factory() as db:
        user_id = add_user(db)

    response = client.get("/admin/dashboard", headers=header_for(user_id))

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_missing_token_gets_401(dashboard_client: DashboardClient) -> None:
    client, _ = dashboard_client

    response = client.get("/admin/dashboard")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_invalid_token_gets_401(dashboard_client: DashboardClient) -> None:
    client, _ = dashboard_client

    response = client.get(
        "/admin/dashboard", headers={"Authorization": "Bearer not-a-jwt"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_recent_reports_exclude_resolved_and_rejected(
    dashboard_client: DashboardClient,
) -> None:
    client, session_factory = dashboard_client
    admin_id = make_admin(session_factory)
    with session_factory() as db:
        reporter = add_user(db)
        pending = add_report(db, reporter, status=ReportStatusEnum.PENDING)
        reviewed = add_report(db, reporter, status=ReportStatusEnum.REVIEWED)
        add_report(db, reporter, status=ReportStatusEnum.RESOLVED)
        add_report(db, reporter, status=ReportStatusEnum.REJECTED)

    response = client.get("/admin/dashboard", headers=header_for(admin_id))

    recent = response.json()["recent_reports"]
    assert {item["report_id"] for item in recent} == {str(pending), str(reviewed)}
    assert {item["status"] for item in recent} == {"PENDING", "REVIEWED"}


def test_recent_reports_are_limited_to_five_newest_first(
    dashboard_client: DashboardClient,
) -> None:
    client, session_factory = dashboard_client
    now = datetime.now(UTC)
    admin_id = make_admin(session_factory)
    # UUID order is the opposite of time order, so sorting by id would fail.
    ids = sorted(uuid4() for _ in range(7))
    with session_factory() as db:
        reporter = add_user(db)
        for index, report_id in enumerate(ids):
            add_report(
                db,
                reporter,
                report_id=report_id,
                opened_at=now - timedelta(hours=len(ids) - index),
            )
        # ids[-1] is the newest (1h ago); ids[0] the oldest (7h ago).

    response = client.get("/admin/dashboard", headers=header_for(admin_id))

    recent = response.json()["recent_reports"]
    assert [item["report_id"] for item in recent] == [
        str(report_id) for report_id in reversed(ids[2:])
    ]


def test_recent_report_resolves_target_name_and_count(
    dashboard_client: DashboardClient,
) -> None:
    client, session_factory = dashboard_client
    now = datetime.now(UTC)
    admin_id = make_admin(session_factory)
    long_description = "Ele mandou mensagens ofensivas no chat do evento. " * 5
    with session_factory() as db:
        reporter = add_user(db)
        person = add_user(db, name="Lucas Ferreira")
        business = add_user(db, name="Bar do Zé", user_type=UserTypeEnum.BUSINESS)
        event = add_event(db, business, "Festa na Cidade Baixa")
        add_report(
            db,
            reporter,
            reported_user_id=person,
            opened_at=now - timedelta(minutes=1),
            description=long_description,
        )
        add_report(
            db,
            reporter,
            reported_user_id=person,
            status=ReportStatusEnum.RESOLVED,
        )
        add_report(
            db,
            reporter,
            reported_user_id=person,
            status=ReportStatusEnum.REVIEWED,
            deleted_at=now,
        )
        add_report(
            db, reporter, reported_user_id=business, opened_at=now - timedelta(hours=1)
        )
        add_report(
            db, reporter, reported_event_id=event, opened_at=now - timedelta(hours=2)
        )

    response = client.get("/admin/dashboard", headers=header_for(admin_id))

    person_item, business_item, event_item = response.json()["recent_reports"]
    assert person_item["target_type"] == "USER"
    assert person_item["target_name"] == "Lucas Ferreira"
    # pending + resolved count; the soft-deleted one does not
    assert person_item["report_count"] == 2
    assert person_item["reason"] == "HARASSMENT"
    assert person_item["status"] == "PENDING"
    assert person_item["description_excerpt"].endswith("...")
    assert len(person_item["description_excerpt"]) == 83
    assert person_item["opened_at"].endswith("Z")
    assert business_item["target_type"] == "BUSINESS"
    assert business_item["target_name"] == "Bar do Zé"
    assert business_item["report_count"] == 1
    assert event_item["target_type"] == "EVENT"
    assert event_item["target_name"] == "Festa na Cidade Baixa"
    assert event_item["description_excerpt"] == "Mensagens ofensivas"