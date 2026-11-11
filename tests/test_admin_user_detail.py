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
    AuditActionEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserRoleEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import AuditLogModel, UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel
from app.main import app

DetailClient = tuple[TestClient, sessionmaker[Session]]

BANNED_AT = datetime(2026, 9, 5, 14, 32, tzinfo=UTC)


@pytest.fixture
def detail_client() -> Iterator[DetailClient]:
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


def get_detail(client: TestClient, admin_id: UUID, user_id: UUID | str):
    return client.get(f"/admin/users/{user_id}", headers=header_for(admin_id))


def add_user(
    db: Session,
    name: str,
    *,
    email: str | None = None,
    role: UserRoleEnum = UserRoleEnum.USER,
    created_at: datetime | None = None,
    deleted_at: datetime | None = None,
    **extra: object,
) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type="PERSONAL",
            role=role,
            email=email or f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
            created_at=created_at or datetime.now(UTC),
            deleted_at=deleted_at,
            **extra,
        )
    )
    db.commit()
    return user_id


def add_admin(db: Session) -> UUID:
    return add_user(db, "Admin", role=UserRoleEnum.ADMIN)


def add_event(
    db: Session,
    creator_id: UUID,
    *,
    event_status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    deleted_at: datetime | None = None,
) -> UUID:
    event_id = uuid4()
    starts_at = datetime.now(UTC) + timedelta(days=1)
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=creator_id,
            event_title="Evento",
            event_latitude=-30.03,
            event_longitude=-51.23,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=3),
            event_status=event_status,
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
    user_id: UUID | None = None,
    event_id: UUID | None = None,
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
    resolution_action: ReportResolutionActionEnum | None = None,
    resolved_by_id: UUID | None = None,
    resolved_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> UUID:
    report_id = uuid4()
    db.add(
        ReportModel(
            report_id=report_id,
            report_creator_id=creator_id,
            reported_user_id=user_id,
            reported_event_id=event_id,
            report_type=ReportTypeEnum.HARASSMENT,
            description="Mensagens ofensivas",
            status=status,
            resolution_action=resolution_action,
            resolved_by_id=resolved_by_id,
            resolved_at=resolved_at,
            deleted_at=deleted_at,
        )
    )
    db.commit()
    return report_id


def add_audit(
    db: Session,
    actor_id: UUID,
    target_id: UUID,
    action: AuditActionEnum,
    created_at: datetime,
) -> None:
    db.add(
        AuditLogModel(
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            created_at=created_at,
        )
    )
    db.commit()


def test_active_user_has_empty_history(detail_client: DetailClient) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_admin(db)
        user_id = add_user(
            db,
            "Lucas Ferreira",
            email="lucas@hangy.com",
            created_at=datetime(2025, 3, 1, tzinfo=UTC),
        )

    response = get_detail(client, admin_id, user_id)

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(user_id),
        "name": "Lucas Ferreira",
        "email": "lucas@hangy.com",
        "member_since": "2025-03-01",
        "moderation_status": "ACTIVE",
        "banned_at": None,
        "suspended_until": None,
        "metrics": {
            "event_count": 0,
            "event_cancelled_count": 0,
            "report_count": 0,
            "report_upheld_count": 0,
        },
        "moderation_history": [],
    }


def test_banned_user_has_banned_at_and_the_ban_in_the_history(
    detail_client: DetailClient,
) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_admin(db)
        creator_id = add_user(db, "Denunciante")
        user_id = add_user(db, "Lucas Ferreira", banned_at=BANNED_AT)
        report_id = add_report(
            db,
            creator_id,
            user_id=user_id,
            status=ReportStatusEnum.RESOLVED,
            resolution_action=ReportResolutionActionEnum.BANNED,
            resolved_by_id=admin_id,
            resolved_at=BANNED_AT,
        )
        add_audit(db, admin_id, user_id, AuditActionEnum.USER_BANNED, BANNED_AT)

    body = get_detail(client, admin_id, user_id).json()

    assert body["moderation_status"] == "BANNED"
    assert datetime.fromisoformat(body["banned_at"]) == BANNED_AT
    assert len(body["moderation_history"]) == 1
    entry = body["moderation_history"][0]
    assert entry["action"] == "BANNED"
    assert entry["actor"] == {"id": str(admin_id), "name": "Admin"}
    assert entry["report_id"] == str(report_id)
    assert datetime.fromisoformat(entry["occurred_at"]) == BANNED_AT


def test_history_is_newest_first_and_only_has_moderation_actions(
    detail_client: DetailClient,
) -> None:
    client, session_factory = detail_client
    day = datetime(2026, 9, 1, tzinfo=UTC)
    with session_factory() as db:
        admin_id = add_admin(db)
        user_id = add_user(db, "Lucas")
        add_audit(db, admin_id, user_id, AuditActionEnum.USER_SUSPENDED, day)
        add_audit(
            db, admin_id, user_id, AuditActionEnum.USER_REVERTED, day + timedelta(days=1)
        )
        add_audit(
            db, admin_id, user_id, AuditActionEnum.USER_BANNED, day + timedelta(days=2)
        )
        add_audit(
            db, admin_id, user_id, AuditActionEnum.TAG_CREATED, day + timedelta(days=3)
        )
        other_id = add_user(db, "Outra pessoa")
        add_audit(
            db, admin_id, other_id, AuditActionEnum.USER_BANNED, day + timedelta(days=4)
        )

    body = get_detail(client, admin_id, user_id).json()

    assert [item["action"] for item in body["moderation_history"]] == [
        "BANNED",
        "REVERTED",
        "SUSPENDED",
    ]
    assert all(item["report_id"] is None for item in body["moderation_history"])


def test_metrics_ignore_archived_deleted_and_other_users(
    detail_client: DetailClient,
) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_admin(db)
        creator_id = add_user(db, "Denunciante")
        user_id = add_user(db, "Lucas")
        other_id = add_user(db, "Outra pessoa")

        add_event(db, user_id)
        add_event(db, user_id)
        cancelled_id = add_event(
            db, user_id, event_status=EventStatusEnum.CANCELLED
        )
        add_event(db, user_id, deleted_at=datetime.now(UTC))
        other_event_id = add_event(db, other_id)

        upheld = ReportResolutionActionEnum
        add_report(
            db,
            creator_id,
            user_id=user_id,
            status=ReportStatusEnum.RESOLVED,
            resolution_action=upheld.BANNED,
        )
        add_report(
            db,
            creator_id,
            user_id=user_id,
            status=ReportStatusEnum.RESOLVED,
            resolution_action=upheld.SUSPENDED,
        )
        add_report(
            db,
            creator_id,
            user_id=user_id,
            status=ReportStatusEnum.REJECTED,
            resolution_action=upheld.ARCHIVED,
        )
        add_report(db, creator_id, user_id=user_id)
        add_report(db, creator_id, event_id=cancelled_id)
        add_report(db, creator_id, user_id=user_id, deleted_at=datetime.now(UTC))
        add_report(db, creator_id, user_id=other_id)
        add_report(db, creator_id, event_id=other_event_id)

    metrics = get_detail(client, admin_id, user_id).json()["metrics"]

    assert metrics == {
        "event_count": 3,
        "event_cancelled_count": 1,
        "report_count": 4,
        "report_upheld_count": 2,
    }


def test_running_suspension_shows_its_end_date(detail_client: DetailClient) -> None:
    client, session_factory = detail_client
    until = datetime.now(UTC) + timedelta(days=5)
    with session_factory() as db:
        admin_id = add_admin(db)
        user_id = add_user(db, "Lucas", suspended_until=until)

    body = get_detail(client, admin_id, user_id).json()

    assert body["moderation_status"] == "SUSPENDED"
    assert datetime.fromisoformat(body["suspended_until"]) == until
    assert body["banned_at"] is None


def test_elapsed_suspension_is_active_again(detail_client: DetailClient) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_admin(db)
        user_id = add_user(
            db, "Lucas", suspended_until=datetime.now(UTC) - timedelta(days=1)
        )

    body = get_detail(client, admin_id, user_id).json()

    assert body["moderation_status"] == "ACTIVE"
    assert body["suspended_until"] is None


def test_unknown_user_returns_404(detail_client: DetailClient) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_admin(db)

    response = get_detail(client, admin_id, uuid4())

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found"}


def test_deleted_user_returns_404(detail_client: DetailClient) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_admin(db)
        user_id = add_user(db, "Excluída", deleted_at=datetime.now(UTC))

    response = get_detail(client, admin_id, user_id)

    assert response.status_code == 404


def test_non_admin_receives_403(detail_client: DetailClient) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        common_id = add_user(db, "Comum")
        user_id = add_user(db, "Lucas")

    response = get_detail(client, common_id, user_id)

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_missing_token_receives_401(detail_client: DetailClient) -> None:
    client, _ = detail_client

    response = client.get(f"/admin/users/{uuid4()}")

    assert response.status_code == 401