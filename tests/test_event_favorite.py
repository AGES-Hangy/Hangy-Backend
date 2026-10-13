from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
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
    EventFavoriteModel,
    EventModel,
    EventParticipantModel,
    NotificationModel,
    UserModel,
)
from app.infrastructure.repository.models.user_block_model import UserBlockModel
from app.main import app

STARTS_AT = datetime.now(UTC) + timedelta(days=5)
NOT_FOUND = {"detail": "Event not found"}


@pytest.fixture
def client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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
        yield test_client, testing_session
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


def _add_user(
    db: Session, name: str, user_type: UserTypeEnum = UserTypeEnum.PERSONAL
) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=user_type,
            role=UserRoleEnum.USER,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
        )
    )
    db.flush()
    return user_id


def _add_event(
    db: Session,
    creator_id: UUID,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    deleted_at: datetime | None = None,
) -> UUID:
    event_id = uuid4()
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=creator_id,
            event_title="Pelada no Parcão",
            event_latitude=-30.0277,
            event_longitude=-51.2287,
            location_name="Parcão",
            starts_at=STARTS_AT,
            ends_at=STARTS_AT + timedelta(hours=3),
            event_status=status,
            event_privacy=privacy,
            deleted_at=deleted_at,
        )
    )
    db.flush()
    return event_id


def _favorites(session_factory: sessionmaker[Session], user_id: UUID) -> int:
    with session_factory() as db:
        return db.scalar(
            select(func.count())
            .select_from(EventFavoriteModel)
            .where(EventFavoriteModel.user_id == user_id)
        )


def _interests(client: TestClient, user_id: UUID) -> list[str]:
    response = client.get(f"/users/{user_id}/events", headers=_authorization(user_id))
    assert response.status_code == 200
    return [item["event_id"] for item in response.json()["interests"]["items"]]


def _is_favorited(client: TestClient, event_id: UUID, user_id: UUID) -> bool:
    response = client.get(f"/events/{event_id}", headers=_authorization(user_id))
    assert response.status_code == 200
    return response.json()["viewer"]["is_favorited"]


def test_favorite_and_unfavorite_drive_interests_and_is_favorited(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_id = _add_user(db, "Felipe")
        organizer_id = _add_user(db, "Organizadora")
        event_id = _add_event(db, organizer_id)
        db.commit()
    headers = _authorization(user_id)

    assert _is_favorited(test_client, event_id, user_id) is False
    assert _interests(test_client, user_id) == []

    favorited = test_client.post(f"/events/{event_id}/favorite", headers=headers)

    assert favorited.status_code == 204
    assert favorited.content == b""
    assert _is_favorited(test_client, event_id, user_id) is True
    assert _interests(test_client, user_id) == [str(event_id)]

    unfavorited = test_client.delete(f"/events/{event_id}/favorite", headers=headers)

    assert unfavorited.status_code == 204
    assert unfavorited.content == b""
    assert _is_favorited(test_client, event_id, user_id) is False
    assert _interests(test_client, user_id) == []
    # Unfavoriting is a physical delete.
    assert _favorites(session_factory, user_id) == 0


def test_favoriting_twice_keeps_a_single_favorite(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_id = _add_user(db, "Felipe")
        event_id = _add_event(db, _add_user(db, "Organizadora"))
        db.commit()
    headers = _authorization(user_id)

    first = test_client.post(f"/events/{event_id}/favorite", headers=headers)
    second = test_client.post(f"/events/{event_id}/favorite", headers=headers)

    assert (first.status_code, second.status_code) == (204, 204)
    assert _favorites(session_factory, user_id) == 1
    # The session survived the duplicate: the favorite is still readable.
    assert _is_favorited(test_client, event_id, user_id) is True


def test_unfavoriting_an_event_that_was_not_favorited_returns_204(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_id = _add_user(db, "Felipe")
        event_id = _add_event(db, _add_user(db, "Organizadora"))
        db.commit()

    response = test_client.delete(
        f"/events/{event_id}/favorite", headers=_authorization(user_id)
    )

    assert response.status_code == 204
    assert _favorites(session_factory, user_id) == 0


def test_favorite_belongs_only_to_the_user_who_made_it(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_id = _add_user(db, "Felipe")
        other_id = _add_user(db, "Outra pessoa")
        event_id = _add_event(db, _add_user(db, "Organizadora"))
        db.commit()

    test_client.post(f"/events/{event_id}/favorite", headers=_authorization(user_id))

    assert _is_favorited(test_client, event_id, other_id) is False
    assert _interests(test_client, other_id) == []
    # Nor does unfavoriting as someone else take it away.
    test_client.delete(f"/events/{event_id}/favorite", headers=_authorization(other_id))
    assert _interests(test_client, user_id) == [str(event_id)]


def test_creator_can_favorite_their_own_event_and_nobody_is_notified(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        organizer_id = _add_user(db, "Organizadora")
        event_id = _add_event(db, organizer_id)
        db.commit()

    response = test_client.post(
        f"/events/{event_id}/favorite", headers=_authorization(organizer_id)
    )

    assert response.status_code == 204
    assert _interests(test_client, organizer_id) == [str(event_id)]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(NotificationModel)) == 0


@pytest.mark.parametrize(
    ("privacy", "joined"),
    [
        # Discoverable like in the feed, so it can be an interest too.
        (EventPrivacyEnum.PRIVATE, False),
        (EventPrivacyEnum.INVITE_ONLY, True),
    ],
)
def test_favorites_follow_the_event_details_visibility(
    client: tuple[TestClient, sessionmaker[Session]],
    privacy: EventPrivacyEnum,
    joined: bool,
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_id = _add_user(db, "Felipe")
        event_id = _add_event(db, _add_user(db, "Organizadora"), privacy=privacy)
        if joined:
            db.add(
                EventParticipantModel(
                    event_id=event_id,
                    user_id=user_id,
                    status=EventParticipantStatusEnum.CONFIRMED,
                )
            )
        db.commit()

    response = test_client.post(
        f"/events/{event_id}/favorite", headers=_authorization(user_id)
    )

    assert response.status_code == 204
    assert _interests(test_client, user_id) == [str(event_id)]


@pytest.mark.parametrize("method", ["post", "delete"])
@pytest.mark.parametrize(
    "event_kwargs",
    [
        {"status": EventStatusEnum.CANCELLED},
        {"status": EventStatusEnum.DRAFT},
        {"deleted_at": STARTS_AT},
        {"privacy": EventPrivacyEnum.INVITE_ONLY},
    ],
)
def test_event_that_cannot_be_seen_returns_404(
    client: tuple[TestClient, sessionmaker[Session]],
    method: str,
    event_kwargs: dict[str, Any],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_id = _add_user(db, "Felipe")
        event_id = _add_event(db, _add_user(db, "Organizadora"), **event_kwargs)
        db.commit()

    response = test_client.request(
        method, f"/events/{event_id}/favorite", headers=_authorization(user_id)
    )

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert _favorites(session_factory, user_id) == 0


@pytest.mark.parametrize("method", ["post", "delete"])
def test_unknown_event_returns_404(
    client: tuple[TestClient, sessionmaker[Session]],
    method: str,
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_id = _add_user(db, "Felipe")
        db.commit()

    response = test_client.request(
        method, f"/events/{uuid4()}/favorite", headers=_authorization(user_id)
    )

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_event_of_an_organizer_who_blocked_the_user_returns_404(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        user_id = _add_user(db, "Felipe")
        organizer_id = _add_user(db, "Organizadora")
        event_id = _add_event(db, organizer_id)
        db.add(UserBlockModel(blocker_id=organizer_id, blocked_id=user_id))
        db.commit()

    response = test_client.post(
        f"/events/{event_id}/favorite", headers=_authorization(user_id)
    )

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_organizer_cannot_favorite_their_own_draft(
    client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        organizer_id = _add_user(db, "Organizadora")
        event_id = _add_event(db, organizer_id, status=EventStatusEnum.DRAFT)
        db.commit()

    response = test_client.post(
        f"/events/{event_id}/favorite", headers=_authorization(organizer_id)
    )

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("method", ["post", "delete"])
def test_business_account_cannot_favorite(
    client: tuple[TestClient, sessionmaker[Session]],
    method: str,
) -> None:
    test_client, session_factory = client
    with session_factory() as db:
        business_id = _add_user(db, "Bar", user_type=UserTypeEnum.BUSINESS)
        event_id = _add_event(db, _add_user(db, "Organizadora"))
        db.commit()

    response = test_client.request(
        method, f"/events/{event_id}/favorite", headers=_authorization(business_id)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only personal accounts can favorite events"}
    assert _favorites(session_factory, business_id) == 0


@pytest.mark.parametrize("method", ["post", "delete"])
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}])
def test_favorite_requires_a_valid_token(
    client: tuple[TestClient, sessionmaker[Session]],
    method: str,
    headers: dict[str, str],
) -> None:
    test_client, _ = client

    response = test_client.request(
        method, f"/events/{uuid4()}/favorite", headers=headers
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
