"""Fixtures and builders shared by the regression tests of the review fixes."""

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
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services.auth import password_hash
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    UserModel,
)
from app.main import app

TERMS_VERSION = settings.terms_version
PASSWORD = "senha-forte-123"
ReviewClient = tuple[TestClient, sessionmaker[Session]]


@pytest.fixture
def review_client() -> Iterator[ReviewClient]:
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
    # Server errors become 500 responses, so a regression shows as a status.
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, session_factory
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(engine)
    engine.dispose()


def headers_for(user_id: UUID) -> dict[str, str]:
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
    user_type: UserTypeEnum = UserTypeEnum.PERSONAL,
    name: str = "Pessoa",
    email: str | None = None,
    banned_at: datetime | None = None,
    password: str | None = None,
) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=user_type,
            role=role,
            email=email or f"{user_id}@hangy.test",
            password_hash=password_hash.hash(password) if password else "hash",
            name=name,
            banned_at=banned_at,
        )
    )
    db.commit()
    return user_id


def add_event(
    db: Session,
    organizer_id: UUID,
    *,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    title: str = "Encontro de teste",
    cover_photo_url: str | None = None,
) -> UUID:
    event_id = uuid4()
    starts_at = starts_at or datetime.now(UTC) + timedelta(days=1)
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=organizer_id,
            event_title=title,
            event_latitude=-30.0,
            event_longitude=-51.0,
            approx_latitude=-30.0,
            approx_longitude=-51.0,
            starts_at=starts_at,
            ends_at=ends_at or starts_at + timedelta(hours=2),
            event_status=status,
            event_privacy=privacy,
            cover_photo_url=cover_photo_url,
        )
    )
    db.commit()
    return event_id


def ended_event(db: Session, organizer_id: UUID, **kwargs: object) -> UUID:
    """An event whose end time passed but nobody marked FINISHED."""
    now = datetime.now(UTC)
    return add_event(
        db,
        organizer_id,
        starts_at=now - timedelta(hours=3),
        ends_at=now - timedelta(hours=1),
        **kwargs,
    )


def add_participant(
    db: Session,
    event_id: UUID,
    user_id: UUID,
    status: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> UUID:
    participant = EventParticipantModel(
        event_id=event_id, user_id=user_id, status=status
    )
    db.add(participant)
    db.commit()
    return participant.participant_id


def valid_cpf(seed: int) -> str:
    base = [int(digit) for digit in f"{seed:09d}"[-9:]]
    for size in (9, 10):
        total = sum(d * w for d, w in zip(base, range(size + 1, 1, -1), strict=True))
        base.append(0 if total % 11 < 2 else 11 - total % 11)
    return "".join(map(str, base))


def personal_payload(email: str, seed: int = 123456789) -> dict[str, object]:
    return {
        "user_type": "PERSONAL",
        "email": email,
        "password": PASSWORD,
        "name": "Ana Souza",
        "cpf": valid_cpf(seed),
        "date_of_birth": "2000-04-12",
        "state": "RS",
        "city": "Porto Alegre",
        "accepted_terms_version": TERMS_VERSION,
    }
