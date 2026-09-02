import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
    UserModel,
    event_tag,
    user_tag,
)
from app.main import app

USER_EMAIL = "felipe@hangy.com"
USER_PASSWORD = "strong-password"
NOW = datetime.now(UTC)


@dataclass(frozen=True)
class FeedContext:
    client: TestClient
    db: Session
    token: str
    user_id: uuid.UUID

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def context() -> Iterator[FeedContext]:
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
    with testing_session() as db, TestClient(app) as client:
        register = client.post(
            "/register",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert register.status_code == 201
        login = client.post(
            "/login",
            data={"username": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert login.status_code == 200
        yield FeedContext(
            client=client,
            db=db,
            token=login.json()["access_token"],
            user_id=uuid.UUID(register.json()["user_id"]),
        )
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_user(db: Session, email: str) -> uuid.UUID:
    user = UserModel(
        user_type=UserTypeEnum.PERSONAL,
        email=email,
        password_hash="hashed",
    )
    db.add(user)
    db.commit()
    return user.user_id


def create_tag(db: Session, name: str, parent_id: uuid.UUID | None = None) -> uuid.UUID:
    tag = TagModel(tag_name=name, tag_parent_id=parent_id)
    db.add(tag)
    db.commit()
    return tag.tag_id


def add_interest(db: Session, user_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    db.execute(user_tag.insert().values(user_id=user_id, tag_id=tag_id))
    db.commit()


def create_event(
    db: Session,
    creator_id: uuid.UUID,
    title: str,
    tag_ids: tuple[uuid.UUID, ...] = (),
    starts_at: datetime | None = None,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    event_status: EventStatusEnum = EventStatusEnum.CREATED,
) -> uuid.UUID:
    starts_at = starts_at if starts_at is not None else NOW + timedelta(days=1)
    event = EventModel(
        event_creator_id=creator_id,
        event_title=title,
        event_latitude=-30.0,
        event_longitude=-51.0,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=2),
        event_status=event_status,
        event_privacy=privacy,
    )
    db.add(event)
    db.commit()
    for tag_id in tag_ids:
        db.execute(event_tag.insert().values(event_id=event.event_id, tag_id=tag_id))
    db.commit()
    return event.event_id


def add_participant(
    db: Session,
    event_id: uuid.UUID,
    user_id: uuid.UUID,
    status: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> None:
    db.add(EventParticipantModel(event_id=event_id, user_id=user_id, status=status))
    db.commit()


def get_feed(context: FeedContext, **params: int) -> dict:
    response = context.client.get("/feed", params=params, headers=context.auth_headers)
    assert response.status_code == 200, response.text
    return response.json()


def titles_by_tag(payload: dict) -> dict[str, list[str]]:
    return {
        section["tag"]["name"]: [item["title"] for item in section["items"]]
        for section in payload["sections"]
    }


def test_feed_returns_only_events_of_the_user_interest_tags(
    context: FeedContext,
) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    football = create_tag(context.db, "Futebol", parent_id=sports)
    music = create_tag(context.db, "Música")
    add_interest(context.db, context.user_id, football)

    create_event(context.db, creator_id, "Pelada no Parcão", (football,))
    create_event(context.db, creator_id, "Show de rock", (music,))
    create_event(context.db, creator_id, "Evento sem tag")

    assert titles_by_tag(get_feed(context)) == {"Esportes": ["Pelada no Parcão"]}


def test_feed_groups_sections_by_macro_tag_and_orders_events_by_date(
    context: FeedContext,
) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    football = create_tag(context.db, "Futebol", parent_id=sports)
    running = create_tag(context.db, "Corrida", parent_id=football)
    music = create_tag(context.db, "Música")
    for tag_id in (football, running, music):
        add_interest(context.db, context.user_id, tag_id)

    create_event(
        context.db,
        creator_id,
        "Pelada no Parcão",
        (football,),
        starts_at=NOW + timedelta(days=3),
    )
    create_event(
        context.db,
        creator_id,
        "Corrida da Redenção",
        (running,),
        starts_at=NOW + timedelta(days=1),
    )
    create_event(context.db, creator_id, "Show de rock", (music,))

    # "Corrida" hangs below "Futebol", so both micro tags roll up to "Esportes".
    assert titles_by_tag(get_feed(context)) == {
        "Esportes": ["Corrida da Redenção", "Pelada no Parcão"],
        "Música": ["Show de rock"],
    }


def test_feed_hides_past_and_unpublished_events(context: FeedContext) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)

    create_event(
        context.db,
        creator_id,
        "Pelada de ontem",
        (sports,),
        starts_at=NOW - timedelta(days=1),
    )
    create_event(
        context.db,
        creator_id,
        "Pelada rascunho",
        (sports,),
        event_status=EventStatusEnum.DRAFT,
    )
    create_event(
        context.db,
        creator_id,
        "Pelada cancelada",
        (sports,),
        event_status=EventStatusEnum.CANCELLED,
    )
    create_event(context.db, creator_id, "Pelada de amanhã", (sports,))

    assert titles_by_tag(get_feed(context)) == {"Esportes": ["Pelada de amanhã"]}


def test_feed_never_shows_invite_only_events(context: FeedContext) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)

    # Even a confirmed participant does not discover it here: an INVITE_ONLY
    # event is only reachable through its invite link.
    event_id = create_event(
        context.db,
        creator_id,
        "Rachão fechado",
        (sports,),
        privacy=EventPrivacyEnum.INVITE_ONLY,
    )
    add_participant(context.db, event_id, context.user_id)

    assert get_feed(context)["sections"] == []


def test_feed_shows_private_events_without_schedule_and_venue(
    context: FeedContext,
) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)

    create_event(
        context.db,
        creator_id,
        "Aniversário do Felipe",
        (sports,),
        privacy=EventPrivacyEnum.PRIVATE,
    )
    create_event(context.db, creator_id, "Pelada no Parcão", (sports,))

    items = {item["title"]: item for item in get_feed(context)["sections"][0]["items"]}

    private_item = items["Aniversário do Felipe"]
    assert private_item["privacy"] == EventPrivacyEnum.PRIVATE
    assert private_item["event_date"] is None
    assert private_item["location_name"] is None
    assert items["Pelada no Parcão"]["event_date"] is not None


def test_feed_hides_a_private_event_schedule_even_from_its_creator(
    context: FeedContext,
) -> None:
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    create_event(
        context.db,
        context.user_id,
        "Aniversário do Felipe",
        (sports,),
        privacy=EventPrivacyEnum.PRIVATE,
    )

    item = get_feed(context)["sections"][0]["items"][0]
    assert item["event_date"] is None


def test_feed_counts_only_confirmed_participants(context: FeedContext) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    pending_id = create_user(context.db, "pending@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)

    event_id = create_event(context.db, creator_id, "Pelada no Parcão", (sports,))
    add_participant(context.db, event_id, creator_id)
    add_participant(
        context.db,
        event_id,
        pending_id,
        status=EventParticipantStatusEnum.PENDING,
    )

    item = get_feed(context)["sections"][0]["items"][0]
    assert item["participants_count"] == 1
    assert item["privacy"] == EventPrivacyEnum.PUBLIC


def test_feed_paginates_each_section_on_its_own(context: FeedContext) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    music = create_tag(context.db, "Música")
    add_interest(context.db, context.user_id, sports)
    add_interest(context.db, context.user_id, music)

    for index in range(3):
        create_event(
            context.db,
            creator_id,
            f"Pelada {index}",
            (sports,),
            starts_at=NOW + timedelta(days=index + 1),
        )
    create_event(context.db, creator_id, "Show de rock", (music,))

    payload = get_feed(context, limit=2)
    sections = {section["tag"]["name"]: section for section in payload["sections"]}

    assert [item["title"] for item in sections["Esportes"]["items"]] == [
        "Pelada 0",
        "Pelada 1",
    ]
    assert sections["Esportes"]["has_more"] is True
    assert sections["Música"]["has_more"] is False


def test_feed_is_empty_for_a_user_without_interest_tags(
    context: FeedContext,
) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    create_event(context.db, creator_id, "Pelada no Parcão", (sports,))

    response = context.client.get("/feed", headers=context.auth_headers)

    assert response.status_code == 200
    assert response.json() == {"sections": []}


def test_feed_rejects_a_limit_outside_the_accepted_range(
    context: FeedContext,
) -> None:
    for limit in (0, 51):
        response = context.client.get(
            "/feed",
            params={"limit": limit},
            headers=context.auth_headers,
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid pagination parameters"}


def test_feed_requires_authentication(context: FeedContext) -> None:
    response = context.client.get("/feed")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.skip(
    reason=(
        "USER_BLOCK does not exist in the schema yet; the feed query cannot "
        "filter blocked creators until the blocking task lands."
    )
)
def test_feed_hides_events_created_by_someone_who_blocked_the_user() -> None:
    raise NotImplementedError
