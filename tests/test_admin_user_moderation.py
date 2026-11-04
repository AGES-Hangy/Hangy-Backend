from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.enums import (
    AuditActionEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services.auth import password_hash
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import AuditLogModel, UserModel
from app.infrastructure.repository.models.report_model import ReportModel
from app.main import app

ModerationClient = tuple[TestClient, sessionmaker[Session]]


@pytest.fixture
def moderation_client() -> Iterator[ModerationClient]:
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
    role: UserRoleEnum = UserRoleEnum.USER,
    name: str = "Pessoa",
    banned_at: datetime | None = None,
    suspended_until: datetime | None = None,
) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=UserTypeEnum.PERSONAL,
            role=role,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
            banned_at=banned_at,
            suspended_until=suspended_until,
        )
    )
    db.commit()
    return user_id


def add_report(
    db: Session,
    creator_id: UUID,
    reported_user_id: UUID,
    *,
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
    deleted_at: datetime | None = None,
) -> UUID:
    report_id = uuid4()
    db.add(
        ReportModel(
            report_id=report_id,
            report_creator_id=creator_id,
            reported_user_id=reported_user_id,
            report_type=ReportTypeEnum.HARASSMENT,
            description="Mensagens ofensivas",
            status=status,
            updated_at=datetime.now(UTC),
            deleted_at=deleted_at,
        )
    )
    db.commit()
    return report_id


def admin_headers(session_factory: sessionmaker[Session]) -> dict[str, str]:
    with session_factory() as db:
        return header_for(add_user(db, role=UserRoleEnum.ADMIN))


def audit_rows(session_factory: sessionmaker[Session]) -> list[AuditLogModel]:
    with session_factory() as db:
        return list(db.scalars(select(AuditLogModel)).all())


def report_row(session_factory: sessionmaker[Session], report_id: UUID) -> ReportModel:
    with session_factory() as db:
        report = db.get(ReportModel, report_id)
        assert report is not None
        db.expunge(report)
        return report


def test_ban_sets_banned_at_revokes_access_and_resolves_the_report(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)
        target_token = header_for(target_id)
        report_id = add_report(db, target_id, target_id)

    assert client.get("/users/me", headers=target_token).status_code == 200

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "BAN", "report_id": str(report_id)},
        headers=admin_header,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["moderation_status"] == "BANNED"
    assert body["suspended_until"] is None

    assert client.get("/users/me", headers=target_token).status_code == 401

    report = report_row(session_factory, report_id)
    assert report.status == ReportStatusEnum.RESOLVED
    assert report.resolution_action == "BANNED"
    assert report.resolved_at is not None


def test_ban_without_report_id_touches_no_report(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)
        other_target_id = add_user(db)
        report_id = add_report(db, other_target_id, other_target_id)

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "BAN"},
        headers=admin_header,
    )

    assert response.status_code == 200
    report = report_row(session_factory, report_id)
    assert report.status == ReportStatusEnum.PENDING


def test_suspend_sets_suspended_until_from_duration_days(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)

    before = datetime.now(UTC)
    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "SUSPEND", "duration_days": 7},
        headers=admin_header,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["moderation_status"] == "SUSPENDED"
    suspended_until = datetime.fromisoformat(body["suspended_until"])
    assert before + timedelta(days=6, hours=23) < suspended_until
    assert suspended_until < before + timedelta(days=7, hours=1)


def test_suspend_on_a_banned_account_is_rejected(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db, banned_at=datetime.now(UTC))

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "SUSPEND", "duration_days": 7},
        headers=admin_header,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Account is already banned"}


def test_revert_clears_moderation_and_restores_access(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db, suspended_until=datetime.now(UTC) + timedelta(days=1))
        target_token = header_for(target_id)

    assert client.get("/users/me", headers=target_token).status_code == 401

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "REVERT"},
        headers=admin_header,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["moderation_status"] == "ACTIVE"
    assert body["suspended_until"] is None
    assert client.get("/users/me", headers=target_token).status_code == 200


def test_revert_on_an_active_account_returns_409(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "REVERT"},
        headers=admin_header,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "User is not banned or suspended"}


def test_missing_report_id_returns_404(moderation_client: ModerationClient) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "BAN", "report_id": str(uuid4())},
        headers=admin_header,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Report not found"}


def test_already_resolved_report_returns_409(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)
        report_id = add_report(
            db, target_id, target_id, status=ReportStatusEnum.RESOLVED
        )

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "BAN", "report_id": str(report_id)},
        headers=admin_header,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Report already resolved"}


def test_every_action_records_an_audit_row(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)

    client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "BAN"},
        headers=admin_header,
    )
    [row] = audit_rows(session_factory)
    assert row.action == AuditActionEnum.USER_BANNED
    assert row.target_id == target_id

    client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "REVERT"},
        headers=admin_header,
    )
    rows = audit_rows(session_factory)
    assert len(rows) == 2
    assert rows[1].action == AuditActionEnum.USER_REVERTED


def test_non_admin_gets_403(moderation_client: ModerationClient) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        requester_id = add_user(db)
        target_id = add_user(db)

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "BAN"},
        headers=header_for(requester_id),
    )

    assert response.status_code == 403


def test_moderating_an_unknown_user_returns_404(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)

    response = client.patch(
        f"/admin/users/{uuid4()}/moderation",
        json={"action": "BAN"},
        headers=admin_header,
    )

    assert response.status_code == 404


def test_report_about_another_user_returns_409_and_stays_open(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)
        other_id = add_user(db)
        report_id = add_report(db, target_id, other_id)

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "SUSPEND", "duration_days": 1, "report_id": str(report_id)},
        headers=admin_header,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Report is not about this user"}
    assert report_row(session_factory, report_id).status == ReportStatusEnum.PENDING
    with session_factory() as db:
        target = db.get(UserModel, target_id)
        assert target is not None
        assert target.suspended_until is None
    assert audit_rows(session_factory) == []


def test_admin_cannot_moderate_own_account(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN)
    admin_header = header_for(admin_id)

    response = client.patch(
        f"/admin/users/{admin_id}/moderation",
        json={"action": "BAN"},
        headers=admin_header,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Admins cannot moderate their own account"}
    assert client.get("/users/me", headers=admin_header).status_code == 200


def test_ban_on_a_banned_account_keeps_the_original_ban_date(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    admin_header = admin_headers(session_factory)
    original_ban = datetime(2026, 1, 1, tzinfo=UTC)
    with session_factory() as db:
        target_id = add_user(db, banned_at=original_ban)
        report_id = add_report(db, target_id, target_id)

    response = client.patch(
        f"/admin/users/{target_id}/moderation",
        json={"action": "BAN", "report_id": str(report_id)},
        headers=admin_header,
    )

    assert response.status_code == 200
    with session_factory() as db:
        target = db.get(UserModel, target_id)
        assert target is not None
        assert target.banned_at is not None
        assert target.banned_at.replace(tzinfo=UTC) == original_ban
    assert report_row(session_factory, report_id).status == ReportStatusEnum.RESOLVED


def _login(
    client: TestClient, session_factory: sessionmaker[Session], **kwargs: datetime
) -> Response:
    with session_factory() as db:
        user_id = add_user(db, **kwargs)
        user = db.get(UserModel, user_id)
        assert user is not None
        user.password_hash = password_hash.hash("Senha123!")
        db.commit()
        email = user.email
    return client.post("/auth/login", json={"email": email, "password": "Senha123!"})


@pytest.mark.parametrize(
    "moderation",
    [
        {"banned_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"suspended_until": datetime.now(UTC) + timedelta(days=1)},
    ],
)
def test_moderated_account_cannot_log_in(
    moderation_client: ModerationClient, moderation: dict[str, datetime]
) -> None:
    client, session_factory = moderation_client

    response = _login(client, session_factory, **moderation)

    assert response.status_code == 403
    assert response.json() == {"detail": "Account is banned or suspended"}


def test_elapsed_suspension_can_log_in_again(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client

    response = _login(
        client,
        session_factory,
        suspended_until=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert response.status_code == 200
