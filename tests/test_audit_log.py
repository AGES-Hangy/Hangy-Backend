from collections.abc import Iterator
from contextlib import contextmanager
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
    AuditTargetTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services.audit_logger import AuditLogger
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.audit_log import SqlAlchemyAuditLogRepository
from app.infrastructure.repository.models import AuditLogModel, UserModel
from app.main import app

ADMIN_ID = UUID("0a001000-0000-4000-8000-000000000001")
OTHER_ADMIN_ID = UUID("0a001000-0000-4000-8000-000000000002")
REGULAR_USER_ID = UUID("0a001000-0000-4000-8000-000000000003")
TARGET_USER_ID = UUID("0a001000-0000-4000-8000-000000000004")

URL = "/admin/audit-log"


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def override_get_db() -> Iterator[Session]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@contextmanager
def _session(client: TestClient) -> Iterator[Session]:
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        yield db
    finally:
        generator.close()


def _auth(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=30)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_users(client: TestClient) -> None:
    with _session(client) as db:
        db.add_all(
            [
                UserModel(
                    user_id=ADMIN_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.ADMIN,
                    email="admin@hangy.test",
                    password_hash="hash",
                    name="Marina S.",
                ),
                UserModel(
                    user_id=OTHER_ADMIN_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.ADMIN,
                    email="other-admin@hangy.test",
                    password_hash="hash",
                    name="Carlos Souza",
                ),
                UserModel(
                    user_id=REGULAR_USER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="user@hangy.test",
                    password_hash="hash",
                    name="Felipe",
                ),
                UserModel(
                    user_id=TARGET_USER_ID,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email="target@hangy.test",
                    password_hash="hash",
                    name="Lucas Ferreira",
                ),
            ]
        )
        db.commit()


def _insert_audit_log(
    client: TestClient,
    *,
    actor_id: UUID | None,
    action: AuditActionEnum,
    target_type: AuditTargetTypeEnum,
    target_label: str | None,
    created_at: datetime,
    target_id: UUID | None = None,
) -> None:
    with _session(client) as db:
        db.add(
            AuditLogModel(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id or uuid4(),
                target_label=target_label,
                created_at=created_at,
            )
        )
        db.commit()


# ---------------------------------------------------------------------------
# AuditLogger.record() — the write path, must never raise
# ---------------------------------------------------------------------------


def test_audit_logger_record_writes_row_with_correct_fields(
    client: TestClient,
) -> None:
    _seed_users(client)
    report_id = uuid4()

    with _session(client) as db:
        repository = SqlAlchemyAuditLogRepository(db)
        audit_logger = AuditLogger(repository=repository, label_resolver=repository)
        audit_logger.record(
            actor_id=ADMIN_ID,
            action=AuditActionEnum.USER_BANNED,
            target_type=AuditTargetTypeEnum.USER,
            target_id=TARGET_USER_ID,
            metadata={"report_id": str(report_id)},
        )
        db.commit()

    with _session(client) as db:
        row = db.query(AuditLogModel).one()
        assert row.actor_id == ADMIN_ID
        assert row.action is AuditActionEnum.USER_BANNED
        assert row.target_type is AuditTargetTypeEnum.USER
        assert row.target_id == TARGET_USER_ID
        # Snapshotted at write time from the target's current name.
        assert row.target_label == "Lucas Ferreira"
        assert row.extra_metadata == {"report_id": str(report_id)}


def test_audit_logger_record_does_not_raise_on_repository_failure() -> None:
    class BrokenWriteRepo:
        def record(self, **kwargs: object) -> UUID:
            raise RuntimeError("DB exploded")

    class NullResolver:
        def resolve(
            self, target_type: AuditTargetTypeEnum, target_id: UUID
        ) -> str | None:
            return None

    audit_logger = AuditLogger(
        repository=BrokenWriteRepo(), label_resolver=NullResolver()
    )

    # Should not raise.
    audit_logger.record(
        actor_id=ADMIN_ID,
        action=AuditActionEnum.USER_BANNED,
        target_type=AuditTargetTypeEnum.USER,
        target_id=TARGET_USER_ID,
    )


# ---------------------------------------------------------------------------
# GET /admin/audit-log
# ---------------------------------------------------------------------------


def test_get_audit_log_returns_newest_first(client: TestClient) -> None:
    _seed_users(client)
    base = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    _insert_audit_log(
        client,
        actor_id=ADMIN_ID,
        action=AuditActionEnum.USER_BANNED,
        target_type=AuditTargetTypeEnum.USER,
        target_label="Oldest",
        created_at=base,
    )
    _insert_audit_log(
        client,
        actor_id=ADMIN_ID,
        action=AuditActionEnum.TAG_CREATED,
        target_type=AuditTargetTypeEnum.TAG,
        target_label="Middle",
        created_at=base + timedelta(hours=1),
    )
    _insert_audit_log(
        client,
        actor_id=ADMIN_ID,
        action=AuditActionEnum.REPORT_ARCHIVED,
        target_type=AuditTargetTypeEnum.REPORT,
        target_label="#aaaaaaaa",
        created_at=base + timedelta(hours=2),
    )

    response = client.get(URL, headers=_auth(ADMIN_ID))

    assert response.status_code == 200
    body = response.json()
    labels = [item["summary"] for item in body["items"]]
    assert len(labels) == 3
    assert "Middle" in labels[1]
    assert "#aaaaaaaa" in labels[0]
    assert "Oldest" in labels[2]


def test_get_audit_log_filters_by_target_type(client: TestClient) -> None:
    _seed_users(client)
    base = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    _insert_audit_log(
        client,
        actor_id=ADMIN_ID,
        action=AuditActionEnum.USER_BANNED,
        target_type=AuditTargetTypeEnum.USER,
        target_label="Lucas Ferreira",
        created_at=base,
    )
    _insert_audit_log(
        client,
        actor_id=ADMIN_ID,
        action=AuditActionEnum.TAG_CREATED,
        target_type=AuditTargetTypeEnum.TAG,
        target_label="Esportes",
        created_at=base + timedelta(hours=1),
    )

    response = client.get(URL, params={"target_type": "TAG"}, headers=_auth(ADMIN_ID))

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["target_type"] == "TAG"
    assert items[0]["summary"] == "Você criou a tag Esportes"


def test_get_audit_log_summary_is_formatted_per_action(client: TestClient) -> None:
    _seed_users(client)
    base = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
    rows = [
        (
            AuditActionEnum.USER_BANNED,
            AuditTargetTypeEnum.USER,
            ADMIN_ID,
            "Lucas Ferreira",
            "Você baniu Lucas Ferreira",
        ),
        (
            AuditActionEnum.USER_SUSPENDED,
            AuditTargetTypeEnum.USER,
            ADMIN_ID,
            "Lucas Ferreira",
            "Você suspendeu Lucas Ferreira",
        ),
        (
            AuditActionEnum.USER_REVERTED,
            AuditTargetTypeEnum.USER,
            ADMIN_ID,
            "Lucas Ferreira",
            "Você reverteu a ação sobre Lucas Ferreira",
        ),
        (
            AuditActionEnum.REPORT_ARCHIVED,
            AuditTargetTypeEnum.REPORT,
            OTHER_ADMIN_ID,
            "#a1b2c3d4",
            "Carlos Souza arquivou a denúncia #a1b2c3d4",
        ),
        (
            AuditActionEnum.TAG_CREATED,
            AuditTargetTypeEnum.TAG,
            ADMIN_ID,
            "Esportes",
            "Você criou a tag Esportes",
        ),
        (
            AuditActionEnum.TAG_UPDATED,
            AuditTargetTypeEnum.TAG,
            ADMIN_ID,
            "Esportes",
            "Você editou a tag Esportes",
        ),
        (
            AuditActionEnum.TAG_DELETED,
            AuditTargetTypeEnum.TAG,
            ADMIN_ID,
            "Esportes",
            "Você removeu a tag Esportes",
        ),
    ]
    for index, (action, target_type, actor_id, label, _expected) in enumerate(rows):
        _insert_audit_log(
            client,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_label=label,
            created_at=base + timedelta(minutes=index),
        )

    response = client.get(URL, headers=_auth(ADMIN_ID))

    assert response.status_code == 200
    items = response.json()["items"]
    summaries_by_action = {item["action"]: item["summary"] for item in items}
    for action, _target_type, _actor_id, _label, expected in rows:
        assert summaries_by_action[action.value] == expected


def test_get_audit_log_requires_admin(client: TestClient) -> None:
    _seed_users(client)

    response = client.get(URL, headers=_auth(REGULAR_USER_ID))

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
