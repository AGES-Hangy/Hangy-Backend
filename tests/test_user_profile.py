from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    UserModel,
)
from app.infrastructure.repository.models.event_experience_model import (
    EventExperienceModel,
)
from app.infrastructure.repository.models.experience_images_model import (
    ExperienceImagesModel,
)
from app.main import app

USER_EMAIL = "ana@hangy.com"
USER_PASSWORD = "strong-password"


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


def register_and_login(client: TestClient) -> tuple[UUID, str]:
    """Register a personal user and return (user_id, access_token)."""
    reg = client.post(
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": USER_EMAIL,
            "password": USER_PASSWORD,
            "name": "Ana Souza",
            "cpf": "52998224725",
            "phone": "51999990000",
            "date_of_birth": "2000-04-12",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": "2026-08-01",
        },
    )
    assert reg.status_code == 201
    login = client.post(
        "/auth/login",
        json={"email": USER_EMAIL, "password": USER_PASSWORD},
    )
    assert login.status_code == 200
    return UUID(reg.json()["user"]["id"]), login.json()["access_token"]


def _create_event(db: Session, creator_id, *, future: bool) -> EventModel:
    now = datetime.now(UTC)
    if future:
        starts = now + timedelta(days=1)
        ends = now + timedelta(days=2)
    else:
        starts = now - timedelta(days=2)
        ends = now - timedelta(days=1)
    event = EventModel(
        event_id=uuid4(),
        event_creator_id=creator_id,
        event_title="Test event",
        event_latitude=0.0,
        event_longitude=0.0,
        starts_at=starts,
        ends_at=ends,
        event_status=EventStatusEnum.PUBLISHED,
        event_privacy=EventPrivacyEnum.PUBLIC,
    )
    db.add(event)
    db.flush()
    return event


def _add_participant(
    db: Session,
    user_id,
    event_id,
    status: EventParticipantStatusEnum,
) -> EventParticipantModel:
    p = EventParticipantModel(
        participant_id=uuid4(),
        user_id=user_id,
        event_id=event_id,
        status=status,
    )
    db.add(p)
    db.flush()
    return p


def _add_photo(db: Session, participant_id) -> None:
    exp = EventExperienceModel(
        experience_id=uuid4(),
        event_participant_id=participant_id,
        description="nice event",
    )
    db.add(exp)
    db.flush()
    img = ExperienceImagesModel(
        photo_id=uuid4(),
        experience_id=exp.experience_id,
        photo_url="https://cdn.example.com/img.jpg",
    )
    db.add(img)
    db.flush()


def _get_db_session(client: TestClient) -> Session:
    gen = app.dependency_overrides[get_db]()
    db = next(gen)
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unauthenticated_request_returns_401(client: TestClient) -> None:
    response = client.get(
        "/users/me/profile", headers={"Authorization": "Bearer invalid"}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_profile_returns_basic_user_data(client: TestClient) -> None:
    user_id, token = register_and_login(client)

    response = client.get(
        "/users/me/profile", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["id"] == str(user_id)
    assert body["profile"]["name"] == "Ana Souza"
    assert body["profile"]["tags"] == []
    assert body["profile"]["connections_count"] == 0
    assert body["counts"] == {"past": 0, "confirmed": 0, "photos": 0}


def test_confirmed_count_includes_only_future_confirmed_events(
    client: TestClient,
) -> None:
    user_id, token = register_and_login(client)
    db = _get_db_session(client)
    try:
        future_event = _create_event(db, user_id, future=True)
        past_event = _create_event(db, user_id, future=False)
        confirmed = EventParticipantStatusEnum.CONFIRMED
        _add_participant(db, user_id, future_event.event_id, confirmed)
        _add_participant(db, user_id, past_event.event_id, confirmed)
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/users/me/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["confirmed"] == 1
    assert counts["past"] == 1


def test_past_count_includes_only_ended_events(client: TestClient) -> None:
    user_id, token = register_and_login(client)
    db = _get_db_session(client)
    try:
        past_event = _create_event(db, user_id, future=False)
        confirmed = EventParticipantStatusEnum.CONFIRMED
        _add_participant(db, user_id, past_event.event_id, confirmed)
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/users/me/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["past"] == 1
    assert counts["confirmed"] == 0


def test_photos_count_only_user_published_images(client: TestClient) -> None:
    user_id, token = register_and_login(client)
    db = _get_db_session(client)
    try:
        past_event = _create_event(db, user_id, future=False)
        participant = _add_participant(
            db, user_id, past_event.event_id, EventParticipantStatusEnum.CONFIRMED
        )
        _add_photo(db, participant.participant_id)
        _add_photo(db, participant.participant_id)
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/users/me/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["counts"]["photos"] == 2


def test_other_user_photos_not_counted(client: TestClient) -> None:
    user_id, token = register_and_login(client)
    db = _get_db_session(client)
    try:
        # Create another user
        other = UserModel(
            user_id=uuid4(),
            user_type=UserTypeEnum.PERSONAL,
            role=UserRoleEnum.USER,
            email="other@hangy.com",
            password_hash="x",
            name="Other",
        )
        db.add(other)
        db.flush()
        past_event = _create_event(db, user_id, future=False)
        other_participant = _add_participant(
            db, other.user_id, past_event.event_id, EventParticipantStatusEnum.CONFIRMED
        )
        _add_photo(db, other_participant.participant_id)
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/users/me/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["counts"]["photos"] == 0


def test_empty_tabs_return_zero_counts(client: TestClient) -> None:
    _, token = register_and_login(client)

    response = client.get(
        "/users/me/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts == {"past": 0, "confirmed": 0, "photos": 0}


def test_pending_participation_not_counted_as_confirmed(client: TestClient) -> None:
    user_id, token = register_and_login(client)
    db = _get_db_session(client)
    try:
        future_event = _create_event(db, user_id, future=True)
        pending = EventParticipantStatusEnum.PENDING
        _add_participant(db, user_id, future_event.event_id, pending)
        db.commit()
    finally:
        db.close()

    response = client.get(
        "/users/me/profile", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["counts"]["confirmed"] == 0
