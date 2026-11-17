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
    AuditActionEnum,
    AuditTargetTypeEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import AuditLogModel, UserModel
from app.infrastructure.repository.models.report_model import ReportModel
from app.main import app

ArchiveClient = tuple[TestClient, sessionmaker[Session]]


@pytest.fixture
def archive_client() -> Iterator[ArchiveClient]:
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


def user_row(session_factory: sessionmaker[Session], user_id: UUID) -> UserModel:
    with session_factory() as db:
        user = db.get(UserModel, user_id)
        assert user is not None
        db.expunge(user)
        return user


@pytest.mark.parametrize(
    "status", [ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED]
)
def test_archiving_an_open_report_rejects_it_with_archived_resolution(
    archive_client: ArchiveClient, status: ReportStatusEnum
) -> None:
    client, session_factory = archive_client
    admin_header = admin_headers(session_factory)
    admin_id = UUID(
        jwt.decode(
            admin_header["Authorization"].removeprefix("Bearer "),
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )["sub"]
    )
    with session_factory() as db:
        target_id = add_user(db)
        report_id = add_report(db, target_id, target_id, status=status)

    response = client.patch(f"/admin/reports/{report_id}/archive", headers=admin_header)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["resolution"]["action"] == "ARCHIVED"
    assert body["resolution"]["resolved_by"]["id"] == str(admin_id)


def test_archiving_does_not_touch_the_reported_account(
    archive_client: ArchiveClient,
) -> None:
    client, session_factory = archive_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)
        report_id = add_report(db, target_id, target_id)

    response = client.patch(f"/admin/reports/{report_id}/archive", headers=admin_header)

    assert response.status_code == 200
    target = user_row(session_factory, target_id)
    assert target.banned_at is None
    assert target.suspended_until is None


def test_archiving_records_an_audit_row(archive_client: ArchiveClient) -> None:
    client, session_factory = archive_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)
        report_id = add_report(db, target_id, target_id)

    client.patch(f"/admin/reports/{report_id}/archive", headers=admin_header)

    [row] = audit_rows(session_factory)
    assert row.action == AuditActionEnum.REPORT_ARCHIVED
    assert row.target_type == AuditTargetTypeEnum.REPORT
    assert row.target_id == report_id


@pytest.mark.parametrize(
    "status", [ReportStatusEnum.RESOLVED, ReportStatusEnum.REJECTED]
)
def test_archiving_an_already_closed_report_returns_409(
    archive_client: ArchiveClient, status: ReportStatusEnum
) -> None:
    client, session_factory = archive_client
    admin_header = admin_headers(session_factory)
    with session_factory() as db:
        target_id = add_user(db)
        report_id = add_report(db, target_id, target_id, status=status)

    response = client.patch(f"/admin/reports/{report_id}/archive", headers=admin_header)

    assert response.status_code == 409
    assert response.json() == {"detail": "Report already resolved"}


def test_missing_report_id_returns_404(archive_client: ArchiveClient) -> None:
    client, session_factory = archive_client
    admin_header = admin_headers(session_factory)

    response = client.patch(f"/admin/reports/{uuid4()}/archive", headers=admin_header)

    assert response.status_code == 404
    assert response.json() == {"detail": "Report not found"}


def test_non_admin_gets_403(archive_client: ArchiveClient) -> None:
    client, session_factory = archive_client
    with session_factory() as db:
        requester_id = add_user(db)
        target_id = add_user(db)
        report_id = add_report(db, target_id, target_id)

    response = client.patch(
        f"/admin/reports/{report_id}/archive", headers=header_for(requester_id)
    )

    assert response.status_code == 403
