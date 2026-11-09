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

DetailClient = tuple[TestClient, sessionmaker[Session]]

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
PHOTO_URL = "https://images.hangy.test/rafael.png"


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


def add_user(
    db: Session,
    *,
    name: str = "Pessoa",
    role: UserRoleEnum = UserRoleEnum.USER,
    user_type: UserTypeEnum = UserTypeEnum.PERSONAL,
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
            created_at=NOW,
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
) -> UUID:
    report_id = uuid4()
    db.add(
        ReportModel(
            report_id=report_id,
            report_creator_id=creator_id,
            reported_user_id=reported_user_id,
            reported_event_id=reported_event_id,
            report_type=ReportTypeEnum.MISLEADING_EVENT,
            description="Denúncia",
            status=status,
            updated_at=NOW,
        )
    )
    db.commit()
    return report_id


def get_detail(client: TestClient, admin_id: UUID, report_id: UUID) -> dict:
    response = client.get(f"/admin/reports/{report_id}", headers=header_for(admin_id))
    assert response.status_code == 200
    return response.json()


def test_event_report_detail_includes_the_organizer_block(
    detail_client: DetailClient,
) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        reporter_id = add_user(db, name="Marina")
        organizer_id = add_user(db, name="Rafael Costa", profile_photo_url=PHOTO_URL)
        event_id = add_event(db, organizer_id)
        add_event(db, organizer_id)
        report_id = add_report(db, reporter_id, reported_event_id=event_id)

    body = get_detail(client, admin_id, report_id)

    assert body["target"]["type"] == "EVENT"
    assert body["organizer"] == {
        "user_id": str(organizer_id),
        "name": "Rafael Costa",
        "photo_url": PHOTO_URL,
        "moderation_status": "ACTIVE",
        "events_count": 2,
        "reports_count": 1,
    }


def test_organizer_counts_follow_the_user_list_rules(
    detail_client: DetailClient,
) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        reporter_id = add_user(db)
        organizer_id = add_user(db, name="Rafael Costa")
        event_id = add_event(db, organizer_id)
        other_event_id = add_event(db, organizer_id)
        add_event(db, organizer_id, deleted_at=NOW)
        report_id = add_report(db, reporter_id, reported_event_id=event_id)
        # Another event and a profile report count; archived ones do not.
        add_report(db, reporter_id, reported_event_id=other_event_id)
        add_report(db, reporter_id, reported_user_id=organizer_id)
        add_report(
            db,
            add_user(db),
            reported_event_id=event_id,
            status=ReportStatusEnum.REJECTED,
        )
        # Somebody else's report never counts.
        add_report(db, reporter_id, reported_user_id=add_user(db))

    organizer = get_detail(client, admin_id, report_id)["organizer"]

    assert organizer["events_count"] == 2
    assert organizer["reports_count"] == 3


def test_organizer_reports_the_moderation_status_and_missing_photo(
    detail_client: DetailClient,
) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        organizer_id = add_user(db, name="Rafael Costa", banned_at=NOW)
        event_id = add_event(db, organizer_id)
        report_id = add_report(db, add_user(db), reported_event_id=event_id)

    organizer = get_detail(client, admin_id, report_id)["organizer"]

    assert organizer["moderation_status"] == "BANNED"
    assert organizer["photo_url"] is None
    assert set(organizer) == {
        "user_id",
        "name",
        "photo_url",
        "moderation_status",
        "events_count",
        "reports_count",
    }


@pytest.mark.parametrize("user_type", [UserTypeEnum.PERSONAL, UserTypeEnum.BUSINESS])
def test_organizer_is_present_only_for_event_targets(
    detail_client: DetailClient, user_type: UserTypeEnum
) -> None:
    client, session_factory = detail_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        target_id = add_user(db, name="Alvo", user_type=user_type)
        report_id = add_report(db, add_user(db), reported_user_id=target_id)

    body = get_detail(client, admin_id, report_id)

    assert body["target"]["type"] == (
        "BUSINESS" if user_type.value == "BUSINESS" else "USER"
    )
    assert "organizer" not in body
