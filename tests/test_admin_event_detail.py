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
    EventModerationStatusEnum,
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserRoleEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventParticipantModel,
    TagModel,
    UserModel,
)
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel
from app.main import app

EventClient = tuple[TestClient, sessionmaker[Session]]

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
STARTS_AT = datetime(2026, 11, 20, 19, 0, tzinfo=UTC)
COVER_URL = "https://cdn.hangy.test/capa.jpg"


@pytest.fixture
def event_client() -> Iterator[EventClient]:
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
    **extra: object,
) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type="PERSONAL",
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


def add_event(db: Session, creator_id: UUID, **extra: object) -> UUID:
    event_id = uuid4()
    fields: dict[str, object] = {
        "event_title": "Jam de rock",
        "event_latitude": -30.0346,
        "event_longitude": -51.2177,
        "approx_latitude": -30.03,
        "approx_longitude": -51.22,
        "starts_at": STARTS_AT,
        "ends_at": STARTS_AT + timedelta(hours=3),
        "event_status": EventStatusEnum.PUBLISHED,
        "event_privacy": EventPrivacyEnum.PRIVATE,
        "created_at": NOW,
    }
    fields.update(extra)
    db.add(EventModel(event_id=event_id, event_creator_id=creator_id, **fields))
    db.commit()
    return event_id


def add_participant(
    db: Session, event_id: UUID, status: EventParticipantStatusEnum
) -> None:
    db.add(
        EventParticipantModel(
            participant_id=uuid4(),
            user_id=add_user(db),
            event_id=event_id,
            status=status,
            joined_at=NOW,
            updated_at=NOW,
        )
    )
    db.commit()


def add_report(
    db: Session,
    *,
    reported_user_id: UUID | None = None,
    reported_event_id: UUID | None = None,
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
    resolution_action: ReportResolutionActionEnum | None = None,
    deleted_at: datetime | None = None,
) -> None:
    db.add(
        ReportModel(
            report_id=uuid4(),
            report_creator_id=add_user(db),
            reported_user_id=reported_user_id,
            reported_event_id=reported_event_id,
            report_type=ReportTypeEnum.MISLEADING_EVENT,
            description="Denúncia",
            status=status,
            resolution_action=resolution_action,
            deleted_at=deleted_at,
            updated_at=NOW,
        )
    )
    db.commit()


def get_detail(client: TestClient, viewer_id: UUID, event_id: UUID | str):
    return client.get(f"/admin/events/{event_id}", headers=header_for(viewer_id))


def test_admin_reads_the_full_event_file(event_client: EventClient) -> None:
    client, session_factory = event_client
    with session_factory() as db:
        admin_id = add_user(db, name="Admin", role=UserRoleEnum.ADMIN)
        organizer_id = add_user(db, name="João Souza")
        event_id = add_event(
            db,
            organizer_id,
            event_description="Som ao vivo no apê.",
            location_name="Apê do João",
            location_neighborhood="Santana",
            location_city="Porto Alegre",
            cover_photo_url=COVER_URL,
            max_participants=20,
        )
        event = db.get(EventModel, event_id)
        assert event is not None
        # Names in reverse alphabetical order: the response sorts them.
        event.tags = [TagModel(tag_name="Rock"), TagModel(tag_name="Música")]
        db.commit()

    response = get_detail(client, admin_id, event_id)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "event_id": str(event_id),
        "title": "Jam de rock",
        "description": "Som ao vivo no apê.",
        "event_date": "2026-11-20T19:00:00Z",
        "end_date": "2026-11-20T22:00:00Z",
        "location_name": "Apê do João",
        "location_neighborhood": "Santana",
        "location_city": "Porto Alegre",
        # A private event: the admin still gets the exact point, not the
        # approximate one the app shows to non-participants.
        "latitude": -30.0346,
        "longitude": -51.2177,
        "privacy": "PRIVATE",
        "status": "PUBLISHED",
        "moderation_status": "ACTIVE",
        "removed_at": None,
        "cover_photo_url": COVER_URL,
        "max_participants": 20,
        "created_at": "2026-11-05T12:00:00Z",
        "tags": ["Música", "Rock"],
        "organizer": {
            "user_id": str(organizer_id),
            "name": "João Souza",
            "photo_url": None,
            "moderation_status": "ACTIVE",
            "event_count": 1,
            "report_count": 0,
        },
        "metrics": {
            "participant_count": 0,
            "pending_count": 0,
            "report_count": 0,
            "report_upheld_count": 0,
        },
    }


def test_metrics_count_participations_and_reports_of_this_event_only(
    event_client: EventClient,
) -> None:
    client, session_factory = event_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN)
        organizer_id = add_user(db)
        event_id = add_event(db, organizer_id)
        other_event_id = add_event(db, organizer_id)

        add_participant(db, event_id, EventParticipantStatusEnum.CONFIRMED)
        add_participant(db, event_id, EventParticipantStatusEnum.CONFIRMED)
        add_participant(db, event_id, EventParticipantStatusEnum.PENDING)
        add_participant(db, event_id, EventParticipantStatusEnum.CANCELLED)
        add_participant(db, other_event_id, EventParticipantStatusEnum.CONFIRMED)

        add_report(db, reported_event_id=event_id)
        add_report(
            db,
            reported_event_id=event_id,
            status=ReportStatusEnum.RESOLVED,
            resolution_action=ReportResolutionActionEnum.EVENT_REMOVED,
        )
        # Archived and deleted reports do not count, nor do other targets.
        add_report(db, reported_event_id=event_id, status=ReportStatusEnum.REJECTED)
        add_report(db, reported_event_id=event_id, deleted_at=NOW)
        add_report(db, reported_event_id=other_event_id)
        # A report against the organizer counts in the organizer's file only.
        add_report(db, reported_user_id=organizer_id)

    body = get_detail(client, admin_id, event_id).json()

    assert body["metrics"] == {
        "participant_count": 2,
        "pending_count": 1,
        "report_count": 2,
        "report_upheld_count": 1,
    }
    assert body["organizer"]["event_count"] == 2
    assert body["organizer"]["report_count"] == 1


def test_removed_event_keeps_its_file(event_client: EventClient) -> None:
    client, session_factory = event_client
    removed_at = datetime(2026, 11, 10, 15, 30, tzinfo=UTC)
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN)
        organizer_id = add_user(db, banned_at=removed_at)
        event_id = add_event(
            db,
            organizer_id,
            moderation_status=EventModerationStatusEnum.REMOVED,
            removed_at=removed_at,
            deleted_at=removed_at,
        )

    response = get_detail(client, admin_id, event_id)

    assert response.status_code == 200
    body = response.json()
    assert body["moderation_status"] == "REMOVED"
    assert body["removed_at"] == "2026-11-10T15:30:00Z"
    assert body["organizer"]["moderation_status"] == "BANNED"


def test_unknown_event_is_404(event_client: EventClient) -> None:
    client, session_factory = event_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN)

    response = get_detail(client, admin_id, uuid4())

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_non_admin_is_forbidden(event_client: EventClient) -> None:
    client, session_factory = event_client
    with session_factory() as db:
        user_id = add_user(db)
        event_id = add_event(db, user_id)

    response = get_detail(client, user_id, event_id)

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_missing_token_is_401(event_client: EventClient) -> None:
    client, _ = event_client

    response = client.get(f"/admin/events/{uuid4()}")

    assert response.status_code == 401
