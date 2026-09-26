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
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    NotificationModel,
    UserModel,
)
from app.main import app


@pytest.fixture
def participation_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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
    with TestClient(app) as client:
        yield client, testing_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _authorization(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def _add_user(db: Session, user_id: UUID, name: str) -> None:
    db.add(
        UserModel(
            user_id=user_id,
            user_type=UserTypeEnum.PERSONAL,
            role=UserRoleEnum.USER,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
        )
    )


def _add_event(
    db: Session,
    event_id: UUID,
    organizer_id: UUID,
    privacy: EventPrivacyEnum,
    *,
    status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    max_participants: int | None = None,
    starts_at: datetime | None = None,
) -> None:
    now = datetime.now(UTC)
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=organizer_id,
            event_title="Encontro de teste",
            event_latitude=0.0,
            event_longitude=0.0,
            starts_at=starts_at or now + timedelta(days=1),
            ends_at=(starts_at or now + timedelta(days=1)) + timedelta(hours=2),
            max_participants=max_participants,
            event_status=status,
            event_privacy=privacy,
        )
    )


def _add_participant(
    db: Session,
    event_id: UUID,
    user_id: UUID,
    status: EventParticipantStatusEnum,
) -> None:
    db.add(EventParticipantModel(event_id=event_id, user_id=user_id, status=status))


def test_public_event_confirms_immediately(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(db, event_id, organizer_id, EventPrivacyEnum.PUBLIC)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CONFIRMED"
    assert "participant_id" in body and "joined_at" in body


def test_private_event_creates_pending_request(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(db, event_id, organizer_id, EventPrivacyEnum.PRIVATE)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"


def test_invite_only_event_is_forbidden(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(db, event_id, organizer_id, EventPrivacyEnum.INVITE_ONLY)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Event is invite-only"


def test_full_public_event_confirmation_is_blocked(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, filler_id, user_id, event_id = uuid4(), uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, filler_id, "Ja confirmado")
        _add_user(db, user_id, "Participante")
        _add_event(
            db, event_id, organizer_id, EventPrivacyEnum.PUBLIC, max_participants=1
        )
        _add_participant(db, event_id, filler_id, EventParticipantStatusEnum.CONFIRMED)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Event is full"


def test_full_private_event_request_is_blocked(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, filler_id, user_id, event_id = uuid4(), uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, filler_id, "Ja confirmado")
        _add_user(db, user_id, "Participante")
        _add_event(
            db, event_id, organizer_id, EventPrivacyEnum.PRIVATE, max_participants=1
        )
        _add_participant(db, event_id, filler_id, EventParticipantStatusEnum.CONFIRMED)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Event is full"


def test_event_without_limit_accepts_confirmation(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(
            db, event_id, organizer_id, EventPrivacyEnum.PUBLIC, max_participants=None
        )
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 201
    assert response.json()["status"] == "CONFIRMED"


def test_second_pending_request_is_rejected(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(db, event_id, organizer_id, EventPrivacyEnum.PRIVATE)
        _add_participant(db, event_id, user_id, EventParticipantStatusEnum.PENDING)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Request already pending"


def test_confirm_after_cancel_reuses_same_row(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(db, event_id, organizer_id, EventPrivacyEnum.PUBLIC)
        _add_participant(db, event_id, user_id, EventParticipantStatusEnum.CANCELLED)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "CONFIRMED"

    with session_factory() as db:
        rows = db.scalars(
            select(EventParticipantModel).where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.user_id == user_id,
            )
        ).all()
        assert len(rows) == 1
        assert str(rows[0].participant_id) == body["participant_id"]


def test_finished_public_event_is_blocked(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(
            db,
            event_id,
            organizer_id,
            EventPrivacyEnum.PUBLIC,
            status=EventStatusEnum.FINISHED,
        )
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Event already finished"


def test_public_confirmation_notifies_organizer(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(db, event_id, organizer_id, EventPrivacyEnum.PUBLIC)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )
    assert response.status_code == 201

    with session_factory() as db:
        notification = db.scalar(
            select(NotificationModel).where(NotificationModel.user_id == organizer_id)
        )
        assert notification is not None
        assert notification.type == NotificationTypeEnum.EVENT_PARTICIPANT_JOINED


def test_private_request_notifies_organizer(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    organizer_id, user_id, event_id = uuid4(), uuid4(), uuid4()
    with session_factory() as db:
        _add_user(db, organizer_id, "Organizador")
        _add_user(db, user_id, "Participante")
        _add_event(db, event_id, organizer_id, EventPrivacyEnum.PRIVATE)
        db.commit()

    response = client.post(
        f"/events/{event_id}/participation", headers=_authorization(user_id)
    )
    assert response.status_code == 201

    with session_factory() as db:
        notification = db.scalar(
            select(NotificationModel).where(NotificationModel.user_id == organizer_id)
        )
        assert notification is not None
        assert notification.type == NotificationTypeEnum.EVENT_PARTICIPATION_REQUEST


def test_event_not_found_returns_404(
    participation_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = participation_client
    user_id = uuid4()
    with session_factory() as db:
        _add_user(db, user_id, "Participante")
        db.commit()

    response = client.post(
        f"/events/{uuid4()}/participation", headers=_authorization(user_id)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Event not found"
