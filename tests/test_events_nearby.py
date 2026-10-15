from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    UserModel,
)
from app.main import app


@pytest.fixture
def events_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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


def _token_for(user_id):
    return jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def _add_event(
    db: Session,
    organizer_id,
    longitude: float,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
) -> EventModel:
    now = datetime.now(UTC)
    event = EventModel(
        event_id=uuid4(),
        event_creator_id=organizer_id,
        event_title=f"Evento {longitude}",
        event_latitude=0,
        event_longitude=longitude,
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
        event_status=EventStatusEnum.PUBLISHED,
        event_privacy=privacy,
        created_at=now,
        updated_at=now,
    )
    db.add(event)
    return event


def test_nearby_events_are_sorted_and_hide_invite_only(
    events_client: tuple[TestClient, object],
) -> None:
    client, session_factory = events_client
    viewer_id = uuid4()
    organizer_ids = [uuid4() for _ in range(4)]
    with session_factory() as db:
        db.add(
            UserModel(
                user_id=viewer_id,
                user_type=UserTypeEnum.PERSONAL,
                role=UserRoleEnum.USER,
                email=f"{viewer_id}@hangy.test",
                password_hash="hash",
            )
        )
        for organizer_id in organizer_ids:
            db.add(
                UserModel(
                    user_id=organizer_id,
                    user_type=UserTypeEnum.PERSONAL,
                    role=UserRoleEnum.USER,
                    email=f"{organizer_id}@hangy.test",
                    password_hash="hash",
                )
            )
        nearest = _add_event(db, organizer_ids[0], 0.01)
        farther = _add_event(db, organizer_ids[1], 0.02)
        outside = _add_event(db, organizer_ids[2], 0.05)
        invite_only = _add_event(
            db, organizer_ids[3], 0.01, EventPrivacyEnum.INVITE_ONLY
        )
        db.add(
            EventParticipantModel(
                user_id=viewer_id,
                event_id=farther.event_id,
                status=EventParticipantStatusEnum.CONFIRMED,
            )
        )
        nearest_id = nearest.event_id
        farther_id = farther.event_id
        outside_id = outside.event_id
        invite_only_id = invite_only.event_id
        db.commit()

    response = client.get(
        "/events/nearby",
        params={"latitude": 0, "longitude": 0, "radius_m": 3_000},
        headers={"Authorization": f"Bearer {_token_for(viewer_id)}"},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["event_id"] for item in items] == [
        str(nearest_id),
        str(farther_id),
    ]
    assert items[0]["distance_m"] < items[1]["distance_m"]
    assert items[1]["is_confirmed"] is True
    assert items[0]["location_precision"] == "EXACT"
    assert items[0]["location_radius_m"] is None
    assert items[0]["privacy"] == "PUBLIC"
    assert str(outside_id) not in {item["event_id"] for item in items}
    assert str(invite_only_id) not in {item["event_id"] for item in items}


def test_nearby_rejects_invalid_coordinates_and_radius(
    events_client: tuple[TestClient, object],
) -> None:
    client, session_factory = events_client
    viewer_id = uuid4()
    with session_factory() as db:
        db.add(
            UserModel(
                user_id=viewer_id,
                user_type=UserTypeEnum.PERSONAL,
                role=UserRoleEnum.USER,
                email=f"{viewer_id}@hangy.test",
                password_hash="hash",
            )
        )
        db.commit()

    headers = {"Authorization": f"Bearer {_token_for(viewer_id)}"}
    invalid_coordinates = client.get(
        "/events/nearby",
        params={"latitude": 91, "longitude": 0, "radius_m": 100},
        headers=headers,
    )
    excessive_radius = client.get(
        "/events/nearby",
        params={"latitude": 0, "longitude": 0, "radius_m": 50_001},
        headers=headers,
    )

    assert invalid_coordinates.status_code == 400
    assert invalid_coordinates.json() == {"detail": "Invalid coordinates"}
    assert excessive_radius.status_code == 400
    assert excessive_radius.json() == {"detail": "Radius exceeds maximum"}
