from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.assemblers import AdminReportAssembler
from app.domain.entities import AdminReportDetailRecord
from app.domain.enums import (
    EventPrivacyEnum,
    EventStatusEnum,
    ModerationStatusEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services import AdminReportsService
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.admin_report import (
    SqlAlchemyAdminReportsRepository,
)
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel
from app.main import app
from app.presentation.routes.admin import get_admin_reports_service
from tests.report_helpers import free_report_type

ReportDetailClient = tuple[TestClient, sessionmaker[Session]]

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def report_detail_client() -> Iterator[ReportDetailClient]:
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
    user_id: UUID | None = None,
    **extra: object,
) -> UUID:
    user_id = user_id or uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=user_type,
            role=role,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
            created_at=created_at or NOW,
            deleted_at=deleted_at,
            **extra,
        )
    )
    db.commit()
    return user_id


def add_event(
    db: Session,
    creator_id: UUID,
    title: str = "Evento",
    *,
    deleted_at: datetime | None = None,
) -> UUID:
    event_id = uuid4()
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=creator_id,
            event_title=title,
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
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
    opened_at: datetime | None = None,
    reported_user_id: UUID | None = None,
    reported_event_id: UUID | None = None,
    report_type: ReportTypeEnum | None = None,
    description: str = "Mensagens ofensivas",
    deleted_at: datetime | None = None,
    report_id: UUID | None = None,
    **extra: object,
) -> UUID:
    report_id = report_id or uuid4()
    report_type = report_type or free_report_type(
        db,
        creator_id,
        reported_user_id=reported_user_id,
        reported_event_id=reported_event_id,
    )
    db.add(
        ReportModel(
            report_id=report_id,
            report_creator_id=creator_id,
            reported_user_id=reported_user_id,
            reported_event_id=reported_event_id,
            report_type=report_type,
            description=description,
            status=status,
            created_at=opened_at or NOW,
            updated_at=opened_at or NOW,
            deleted_at=deleted_at,
            **extra,
        )
    )
    db.commit()
    return report_id


def make_admin(session_factory: sessionmaker[Session]) -> UUID:
    with session_factory() as db:
        return add_user(db, name="Admin", role=UserRoleEnum.ADMIN)


class FakeAdminReportsRepository:
    def __init__(self, record: AdminReportDetailRecord | None) -> None:
        self.record = record

    def get_report_detail(self, report_id: UUID) -> AdminReportDetailRecord | None:
        if self.record is not None and self.record.report_id == report_id:
            return self.record
        return None


def make_record(**overrides: object) -> AdminReportDetailRecord:
    defaults: dict[str, object] = {
        "report_id": uuid4(),
        "report_number": 1042,
        "status": ReportStatusEnum.PENDING,
        "opened_at": NOW,
        "reported_at": NOW,
        "reason": ReportTypeEnum.HARASSMENT,
        "description": "Ele mandou mensagens ofensivas no chat do evento.",
        "reported_event_id": None,
        "target_user_id": uuid4(),
        "target_user_name": "Lucas Ferreira",
        "target_user_type": UserTypeEnum.PERSONAL,
        "target_created_at": datetime(2025, 3, 1, 10, 0, tzinfo=UTC),
        "target_banned_at": None,
        "target_suspended_until": None,
        "target_event_count": 12,
        "reported_by_id": uuid4(),
        "reported_by_name": "Marina S.",
        "previous_archived_count": 1,
        "previous_resolved_count": 1,
        "resolved_by_id": None,
        "resolved_by_name": None,
        "resolved_at": None,
        "resolution_action": None,
    }
    defaults.update(overrides)
    return AdminReportDetailRecord(**defaults)  # type: ignore[arg-type]


def test_pending_report_detail_returns_null_resolution(
    report_detail_client: ReportDetailClient,
) -> None:
    client, session_factory = report_detail_client
    admin_id = make_admin(session_factory)
    opened_at = datetime(2026, 9, 4, 12, 18, tzinfo=UTC)
    member_since = datetime(2025, 3, 1, 15, 0, tzinfo=UTC)
    description = (
        "Ele mandou mensagens ofensivas no chat do evento depois que recusei "
        "a solicitação de conexão. Depois criou outro perfil para insistir."
    )
    with session_factory() as db:
        reporter_id = add_user(db, name="Marina S.")
        target_id = add_user(
            db,
            name="Lucas Ferreira",
            created_at=member_since,
        )
        add_event(db, target_id, "Evento 1")
        add_event(db, target_id, "Evento 2")
        add_event(db, target_id, "Evento deletado", deleted_at=NOW)
        report_id = add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.PENDING,
            opened_at=opened_at,
            report_type=ReportTypeEnum.HARASSMENT,
            description=description,
        )

    response = client.get(
        f"/admin/reports/{report_id}",
        headers=header_for(admin_id),
    )

    assert response.status_code == 200
    assert response.json() == {
        "report_id": str(report_id),
        "report_number": 1,
        "status": "PENDING",
        "opened_at": "2026-09-04T12:18:00Z",
        "target": {
            "type": "USER",
            "id": str(target_id),
            "name": "Lucas Ferreira",
            "member_since": "2025-03-01",
            "event_count": 2,
            "moderation_status": "ACTIVE",
        },
        "reason": "HARASSMENT",
        "description": description,
        "reported_by": {
            "id": str(reporter_id),
            "name": "Marina S.",
        },
        "reported_at": "2026-09-04T12:18:00Z",
        "previous_reports": {
            "total": 0,
            "archived": 0,
            "resolved_with_action": 0,
        },
        "resolution": None,
    }


def test_resolved_report_detail_returns_populated_resolution(
    report_detail_client: ReportDetailClient,
) -> None:
    client, session_factory = report_detail_client
    admin_id = make_admin(session_factory)
    report_id = uuid4()
    target_id = uuid4()
    reporter_id = uuid4()
    resolver_id = uuid4()
    resolved_at = datetime(2026, 9, 22, 14, 32, tzinfo=UTC)
    record = make_record(
        report_id=report_id,
        report_number=1042,
        status=ReportStatusEnum.RESOLVED,
        target_user_id=target_id,
        target_banned_at=resolved_at,
        reported_by_id=reporter_id,
        resolved_by_id=resolver_id,
        resolved_by_name="Gabriel N.",
        resolved_at=resolved_at,
        resolution_action="BANNED",
    )
    app.dependency_overrides[get_admin_reports_service] = lambda: AdminReportsService(
        repository=FakeAdminReportsRepository(record)
    )

    response = client.get(
        f"/admin/reports/{report_id}",
        headers=header_for(admin_id),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RESOLVED"
    assert body["target"]["moderation_status"] == "BANNED"
    assert body["resolution"] == {
        "resolved_by": {
            "id": str(resolver_id),
            "name": "Gabriel N.",
        },
        "resolved_at": "2026-09-22T14:32:00Z",
        "action": "BANNED",
    }


def test_resolved_report_without_resolution_columns_returns_null_resolution(
    report_detail_client: ReportDetailClient,
) -> None:
    client, session_factory = report_detail_client
    admin_id = make_admin(session_factory)
    with session_factory() as db:
        reporter_id = add_user(db, name="Marina S.")
        target_id = add_user(db, name="Lucas Ferreira")
        report_id = add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.RESOLVED,
        )

    response = client.get(
        f"/admin/reports/{report_id}",
        headers=header_for(admin_id),
    )

    assert response.status_code == 200
    assert response.json()["resolution"] is None


def test_previous_reports_counts_closed_reports_excluding_current(
    report_detail_client: ReportDetailClient,
) -> None:
    client, session_factory = report_detail_client
    admin_id = make_admin(session_factory)
    with session_factory() as db:
        reporter_id = add_user(db, name="Marina S.")
        target_id = add_user(db, name="Lucas Ferreira")
        other_user_id = add_user(db, name="Outra Pessoa")
        target_event_id = add_event(db, target_id, "Festa do Lucas")

        # 1 archived (REJECTED) against target profile
        add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.REJECTED,
            opened_at=NOW - timedelta(days=5),
        )
        # 1 resolved (RESOLVED) against target profile
        add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.RESOLVED,
            opened_at=NOW - timedelta(days=4),
        )
        # 1 resolved (RESOLVED) against an event organized by target
        add_report(
            db,
            reporter_id,
            reported_event_id=target_event_id,
            status=ReportStatusEnum.RESOLVED,
            opened_at=NOW - timedelta(days=3),
        )
        # Open / in-review reports must NOT be counted in previous_reports
        add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.PENDING,
            opened_at=NOW - timedelta(days=2),
        )
        add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.REVIEWED,
            opened_at=NOW - timedelta(days=1),
        )
        # Soft-deleted closed report must NOT be counted
        add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.RESOLVED,
            deleted_at=NOW,
        )
        # Closed report against another user must NOT be counted
        add_report(
            db,
            reporter_id,
            reported_user_id=other_user_id,
            status=ReportStatusEnum.RESOLVED,
        )
        # The current report itself (even if RESOLVED) must be excluded
        current_report_id = add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.RESOLVED,
            opened_at=NOW,
        )

    response = client.get(
        f"/admin/reports/{current_report_id}",
        headers=header_for(admin_id),
    )

    assert response.status_code == 200
    assert response.json()["previous_reports"] == {
        "total": 3,
        "archived": 1,
        "resolved_with_action": 2,
    }


def test_event_and_business_targets_resolve_to_responsible_account(
    report_detail_client: ReportDetailClient,
) -> None:
    client, session_factory = report_detail_client
    admin_id = make_admin(session_factory)
    business_joined = datetime(2024, 6, 15, 9, 0, tzinfo=UTC)
    with session_factory() as db:
        reporter_id = add_user(db, name="Marina S.")
        business_id = add_user(
            db,
            name="Bar do Zé",
            user_type=UserTypeEnum.BUSINESS,
            created_at=business_joined,
        )
        event_id = add_event(db, business_id, "Noite do Samba")
        add_event(db, business_id, "Happy Hour")

        event_report_id = add_report(
            db,
            reporter_id,
            reported_event_id=event_id,
            report_type=ReportTypeEnum.MISLEADING_EVENT,
            opened_at=NOW - timedelta(hours=2),
        )
        business_report_id = add_report(
            db,
            reporter_id,
            reported_user_id=business_id,
            report_type=ReportTypeEnum.SPAM,
            status=ReportStatusEnum.REJECTED,
            opened_at=NOW - timedelta(hours=1),
        )

    headers = header_for(admin_id)
    event_resp = client.get(f"/admin/reports/{event_report_id}", headers=headers)
    business_resp = client.get(f"/admin/reports/{business_report_id}", headers=headers)

    assert event_resp.status_code == 200
    assert event_resp.json()["target"] == {
        "type": "EVENT",
        "id": str(business_id),
        "name": "Bar do Zé",
        "member_since": "2024-06-15",
        "event_count": 2,
        "moderation_status": "ACTIVE",
    }
    assert event_resp.json()["previous_reports"] == {
        "total": 1,
        "archived": 1,
        "resolved_with_action": 0,
    }

    assert business_resp.status_code == 200
    assert business_resp.json()["target"] == {
        "type": "BUSINESS",
        "id": str(business_id),
        "name": "Bar do Zé",
        "member_since": "2024-06-15",
        "event_count": 2,
        "moderation_status": "ACTIVE",
    }


def test_report_number_is_the_stored_sequential_number(
    report_detail_client: ReportDetailClient,
) -> None:
    client, session_factory = report_detail_client
    admin_id = make_admin(session_factory)
    smaller_id, larger_id = sorted([uuid4(), uuid4()])
    with session_factory() as db:
        reporter_1 = add_user(db, name="Rep 1")
        reporter_2 = add_user(db, name="Rep 2")
        target_id = add_user(db, name="Lucas Ferreira")
        # Usar criadores diferentes para evitar violação da Unique Constraint
        add_report(db, reporter_1, reported_user_id=target_id, report_id=larger_id)
        add_report(db, reporter_2, reported_user_id=target_id, report_id=smaller_id)

    headers = header_for(admin_id)
    first = client.get(f"/admin/reports/{larger_id}", headers=headers).json()
    second = client.get(f"/admin/reports/{smaller_id}", headers=headers).json()

    assert [first["report_number"], second["report_number"]] == [1, 2]


def test_nonexistent_or_deleted_report_returns_404(
    report_detail_client: ReportDetailClient,
) -> None:
    client, session_factory = report_detail_client
    admin_id = make_admin(session_factory)
    with session_factory() as db:
        reporter_id = add_user(db)
        target_id = add_user(db)
        deleted_report_id = add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            deleted_at=NOW,
        )
        # Passando um alvo válido para satisfazer a constraint, mas podemos testar
        # consultando um UUID gerado aleatoriamente que não existe no banco.
        non_existent_targetless_id = uuid4()

    headers = header_for(admin_id)
    missing = client.get(f"/admin/reports/{uuid4()}", headers=headers)
    deleted = client.get(f"/admin/reports/{deleted_report_id}", headers=headers)
    targetless = client.get(
        f"/admin/reports/{non_existent_targetless_id}", headers=headers
    )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Report not found"}
    assert deleted.status_code == 404
    assert deleted.json() == {"detail": "Report not found"}
    assert targetless.status_code == 404
    assert targetless.json() == {"detail": "Report not found"}


def test_non_admin_receives_403(
    report_detail_client: ReportDetailClient,
) -> None:
    client, session_factory = report_detail_client
    with session_factory() as db:
        user_id = add_user(db, role=UserRoleEnum.USER)

    response = client.get(
        f"/admin/reports/{uuid4()}",
        headers=header_for(user_id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_missing_or_invalid_token_receives_401(
    report_detail_client: ReportDetailClient,
) -> None:
    client, _ = report_detail_client
    report_id = uuid4()

    missing = client.get(f"/admin/reports/{report_id}")
    invalid = client.get(
        f"/admin/reports/{report_id}",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert missing.status_code == 401
    assert missing.json() == {"detail": "Could not validate credentials"}
    assert invalid.status_code == 401
    assert invalid.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize(
    ("banned_at", "suspended_until", "expected"),
    [
        (None, None, ModerationStatusEnum.ACTIVE),
        (None, NOW + timedelta(seconds=1), ModerationStatusEnum.SUSPENDED),
        (None, NOW, ModerationStatusEnum.ACTIVE),
        (None, NOW - timedelta(days=1), ModerationStatusEnum.ACTIVE),
        (NOW - timedelta(days=1), None, ModerationStatusEnum.BANNED),
        (NOW, NOW + timedelta(days=5), ModerationStatusEnum.BANNED),
        (
            None,
            (NOW + timedelta(hours=1)).replace(tzinfo=None),
            ModerationStatusEnum.SUSPENDED,
        ),
    ],
)
def test_service_derives_target_moderation_status(
    banned_at: datetime | None,
    suspended_until: datetime | None,
    expected: ModerationStatusEnum,
) -> None:
    record = make_record(
        target_banned_at=banned_at,
        target_suspended_until=suspended_until,
    )
    service = AdminReportsService(repository=FakeAdminReportsRepository(record))

    detail = service.get_report_detail(record.report_id, now=NOW)

    assert detail.target.moderation_status == expected


def test_repository_reads_explicit_report_number_and_resolver_when_set(
    report_detail_client: ReportDetailClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, session_factory = report_detail_client
    reported_at = datetime(2026, 9, 4, 11, 45)  # naive to verify UTC normalization
    resolved_at = datetime(2026, 9, 22, 14, 32)  # naive to verify UTC normalization
    with session_factory() as db:
        resolver_id = add_user(db, name="Gabriel N.", role=UserRoleEnum.ADMIN)
        reporter_id = add_user(db, name="Marina S.")
        target_id = add_user(
            db,
            name="Lucas Ferreira",
            created_at=datetime(2025, 3, 1, 8, 0),
        )
        report_id = add_report(
            db,
            reporter_id,
            reported_user_id=target_id,
            status=ReportStatusEnum.RESOLVED,
            resolved_by_id=resolver_id,
            resolved_at=resolved_at,
            resolution_action=ReportResolutionActionEnum.BANNED,
            report_number=1042,
        )

        monkeypatch.setattr(ReportModel, "reported_at", reported_at, raising=False)

        repo = SqlAlchemyAdminReportsRepository(db)
        service = AdminReportsService(repository=repo)
        detail = service.get_report_detail(report_id, now=NOW)
        dto = AdminReportAssembler.to_dto(detail)

    assert dto.report_number == 1042
    assert dto.opened_at == NOW
    assert dto.reported_at == datetime(2026, 9, 4, 11, 45, tzinfo=UTC)
    assert dto.target.member_since == date(2025, 3, 1)
    assert dto.resolution is not None
    assert dto.resolution.resolved_by.id == resolver_id
    assert dto.resolution.resolved_by.name == "Gabriel N."
    assert dto.resolution.resolved_at == datetime(2026, 9, 22, 14, 32, tzinfo=UTC)
    assert dto.resolution.action == "BANNED"
