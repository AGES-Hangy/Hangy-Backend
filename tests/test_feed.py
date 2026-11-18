import math
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
    EventFavoriteModel,
    EventModel,
    EventParticipantModel,
    TagModel,
    UserBlockModel,
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
            "/auth/register",
            json={
                "user_type": "PERSONAL",
                "email": USER_EMAIL,
                "password": USER_PASSWORD,
                "name": "Felipe Souza",
                "cpf": "52998224725",
                "phone": "51999990000",
                "date_of_birth": "2000-04-12",
                "state": "RS",
                "city": "Porto Alegre",
                "accepted_terms_version": "2026-08-01",
            },
        )
        assert register.status_code == 201
        login = client.post(
            "/auth/login",
            json={"email": USER_EMAIL, "password": USER_PASSWORD},
        )
        assert login.status_code == 200
        yield FeedContext(
            client=client,
            db=db,
            token=login.json()["access_token"],
            user_id=uuid.UUID(register.json()["user"]["id"]),
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
    event_status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    location_name: str | None = None,
    neighborhood: str | None = None,
    city: str | None = None,
    latitude: float = -30.0,
    longitude: float = -51.0,
    approx_point: tuple[float, float] | None = None,
) -> uuid.UUID:
    starts_at = starts_at if starts_at is not None else NOW + timedelta(days=1)
    approx = (
        {}
        if approx_point is None
        else {"approx_latitude": approx_point[0], "approx_longitude": approx_point[1]}
    )
    event = EventModel(
        event_creator_id=creator_id,
        event_title=title,
        location_name=location_name,
        location_neighborhood=neighborhood,
        location_city=city,
        event_latitude=latitude,
        event_longitude=longitude,
        **approx,
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


def get_feed(context: FeedContext, **params: float) -> dict:
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


def test_feed_item_shows_its_own_matched_tag_not_the_section_macro_tag(
    context: FeedContext,
) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    football = create_tag(context.db, "Futebol", parent_id=sports)
    running = create_tag(context.db, "Corrida", parent_id=sports)
    add_interest(context.db, context.user_id, football)
    add_interest(context.db, context.user_id, running)

    # Tagged with both a micro tag under Esportes and an unrelated one: the
    # card should show only the micro tag that actually put it in this
    # section, not the section's own "Esportes" (that's already the title)
    # nor a tag from a section the viewer has no interest in.
    music = create_tag(context.db, "Música")
    create_event(context.db, creator_id, "Pelada no Parcão", (football, music))

    payload = get_feed(context)
    item = payload["sections"][0]["items"][0]

    assert [tag["name"] for tag in item["tags"]] == ["Futebol"]


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


def test_feed_shows_private_events_without_schedule_and_with_the_neighborhood(
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
        location_name="Rua da Casa, 123",
        neighborhood="Bom Fim",
        city="Porto Alegre",
    )
    create_event(
        context.db,
        creator_id,
        "Pelada no Parcão",
        (sports,),
        location_name="Parcão",
        neighborhood="Moinhos de Vento",
        city="Porto Alegre",
    )

    items = {item["title"]: item for item in get_feed(context)["sections"][0]["items"]}

    private_item = items["Aniversário do Felipe"]
    assert private_item["privacy"] == EventPrivacyEnum.PRIVATE
    assert private_item["event_date"] is None
    assert private_item["location_name"] == "Bom Fim, Porto Alegre"
    assert private_item["location_precision"] == "APPROXIMATE"
    assert items["Pelada no Parcão"]["event_date"] is not None
    assert items["Pelada no Parcão"]["location_name"] == "Parcão"
    assert items["Pelada no Parcão"]["location_precision"] == "EXACT"


@pytest.mark.parametrize(
    ("status", "location_name", "precision"),
    [
        # CONFIRMED never reaches the feed: see the test right below.
        (EventParticipantStatusEnum.PENDING, "Bom Fim, Porto Alegre", "APPROXIMATE"),
        (EventParticipantStatusEnum.REMOVED, "Bom Fim, Porto Alegre", "APPROXIMATE"),
    ],
)
def test_feed_resolves_a_private_event_location_from_the_viewer_participation(
    context: FeedContext,
    status: EventParticipantStatusEnum,
    location_name: str,
    precision: str,
) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    other_id = create_user(context.db, "other@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    event_id = create_event(
        context.db,
        creator_id,
        "Aniversário do Felipe",
        (sports,),
        privacy=EventPrivacyEnum.PRIVATE,
        location_name="Rua da Casa, 123",
        neighborhood="Bom Fim",
        city="Porto Alegre",
    )
    add_participant(context.db, event_id, context.user_id, status=status)
    # Someone else's approval must not leak the address to this viewer, nor
    # duplicate the card.
    add_participant(context.db, event_id, other_id)

    [item] = get_feed(context)["sections"][0]["items"]

    assert item["location_name"] == location_name
    assert item["location_precision"] == precision
    assert item["participants_count"] == 1


def test_feed_hides_events_the_viewer_already_confirmed(
    context: FeedContext,
) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    confirmed_id = create_event(context.db, creator_id, "Pelada confirmada", (sports,))
    pending_id = create_event(context.db, creator_id, "Pelada pendente", (sports,))
    add_participant(context.db, confirmed_id, context.user_id)
    add_participant(
        context.db,
        pending_id,
        context.user_id,
        status=EventParticipantStatusEnum.PENDING,
    )

    assert titles_by_tag(get_feed(context)) == {"Esportes": ["Pelada pendente"]}


def test_feed_private_event_without_neighborhood_has_no_location_name(
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
        location_name="Rua da Casa, 123",
    )

    item = get_feed(context)["sections"][0]["items"][0]

    assert item["location_name"] is None
    assert item["location_precision"] == "APPROXIMATE"


def test_feed_hides_the_viewer_own_events(context: FeedContext) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    create_event(context.db, context.user_id, "Minha pelada", (sports,))
    create_event(
        context.db,
        context.user_id,
        "Meu aniversário",
        (sports,),
        privacy=EventPrivacyEnum.PRIVATE,
    )
    create_event(context.db, creator_id, "Pelada de outra pessoa", (sports,))

    assert titles_by_tag(get_feed(context)) == {"Esportes": ["Pelada de outra pessoa"]}


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


def test_feed_tells_which_events_the_viewer_favorited(context: FeedContext) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    other_id = create_user(context.db, "other@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)

    favorited_id = create_event(
        context.db, creator_id, "Pelada no Parcão", (sports,), NOW + timedelta(days=1)
    )
    other_favorite_id = create_event(
        context.db, creator_id, "Vôlei na Redenção", (sports,), NOW + timedelta(days=2)
    )
    context.db.add(EventFavoriteModel(event_id=favorited_id, user_id=context.user_id))
    # Someone else's favorite must not leak into the viewer's feed.
    context.db.add(EventFavoriteModel(event_id=other_favorite_id, user_id=other_id))
    context.db.commit()

    items = get_feed(context)["sections"][0]["items"]
    assert {item["title"]: item["is_favorited"] for item in items} == {
        "Pelada no Parcão": True,
        "Vôlei na Redenção": False,
    }


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


def test_feed_rejects_an_invalid_token(context: FeedContext) -> None:
    response = context.client.get("/feed", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("privacy", "location_name", "precision"),
    [
        (EventPrivacyEnum.PUBLIC, "Parque", "EXACT"),
        (EventPrivacyEnum.PRIVATE, None, "APPROXIMATE"),
    ],
)
def test_newly_published_event_is_discoverable_with_appropriate_location(
    context: FeedContext,
    privacy: EventPrivacyEnum,
    location_name: str | None,
    precision: str,
) -> None:
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    response = context.client.post(
        "/events",
        headers=context.auth_headers,
        json={
            "title": "New event",
            "event_date": (NOW + timedelta(days=2)).isoformat(),
            "end_date": (NOW + timedelta(days=2, hours=2)).isoformat(),
            "location": {"latitude": -30.0, "longitude": -51.0},
            "location_name": "Parque",
            "privacy": privacy.value,
            "tag_ids": [str(sports)],
        },
    )
    assert response.status_code == 201, response.text
    # The organizer never sees their own event in the feed: someone else does.
    assert get_feed(context)["sections"] == []
    register = context.client.post(
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": "visitor@hangy.com",
            "password": USER_PASSWORD,
            "name": "Visitante",
            "cpf": "11144477735",
            "phone": "51999990001",
            "date_of_birth": "2000-04-12",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": "2026-08-01",
        },
    )
    assert register.status_code == 201, register.text
    add_interest(context.db, uuid.UUID(register.json()["user"]["id"]), sports)
    login = context.client.post(
        "/auth/login",
        json={"email": "visitor@hangy.com", "password": USER_PASSWORD},
    )
    visitor = FeedContext(
        client=context.client,
        db=context.db,
        token=login.json()["access_token"],
        user_id=uuid.UUID(register.json()["user"]["id"]),
    )

    item = get_feed(visitor)["sections"][0]["items"][0]
    assert item["title"] == "New event"
    assert item["location_name"] == location_name
    assert item["location_precision"] == precision


def test_feed_hides_events_created_by_someone_who_blocked_the_user(
    context: FeedContext,
) -> None:
    blocker_id = create_user(context.db, "blocker@hangy.com")
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    create_event(context.db, blocker_id, "Pelada de quem me bloqueou", (sports,))
    create_event(context.db, creator_id, "Pelada liberada", (sports,))
    context.db.add(UserBlockModel(blocker_id=blocker_id, blocked_id=context.user_id))
    context.db.commit()

    assert titles_by_tag(get_feed(context)) == {"Esportes": ["Pelada liberada"]}


def test_feed_hides_events_created_by_someone_the_user_blocked(
    context: FeedContext,
) -> None:
    blocked_id = create_user(context.db, "blocked@hangy.com")
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    create_event(context.db, blocked_id, "Pelada de quem bloqueei", (sports,))
    create_event(context.db, creator_id, "Pelada liberada", (sports,))
    context.db.add(UserBlockModel(blocker_id=context.user_id, blocked_id=blocked_id))
    context.db.commit()

    assert titles_by_tag(get_feed(context)) == {"Esportes": ["Pelada liberada"]}


def test_feed_keeps_events_when_the_block_involves_other_users(
    context: FeedContext,
) -> None:
    creator_id = create_user(context.db, "creator@hangy.com")
    other_id = create_user(context.db, "other@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    create_event(context.db, creator_id, "Pelada liberada", (sports,))
    context.db.add(UserBlockModel(blocker_id=creator_id, blocked_id=other_id))
    context.db.commit()

    assert titles_by_tag(get_feed(context)) == {"Esportes": ["Pelada liberada"]}


# Porto Alegre, where the viewer is; the other points are real cities around it.
PORTO_ALEGRE = (-30.0346, -51.2177)
CANOAS = (-29.9178, -51.1839)  # ~13 km
GRAVATAI = (-29.9440, -50.9919)  # ~24 km
SAO_PAULO = (-23.5505, -46.6333)  # ~850 km


def feed_near(context: FeedContext, point: tuple[float, float], **params: float):
    return get_feed(context, latitude=point[0], longitude=point[1], **params)


def sports_interest(context: FeedContext) -> tuple[uuid.UUID, uuid.UUID]:
    creator_id = create_user(context.db, "creator@hangy.com")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)
    return creator_id, sports


def create_event_at(
    context: FeedContext,
    creator_id: uuid.UUID,
    tag_id: uuid.UUID,
    title: str,
    point: tuple[float, float],
    **kwargs,
) -> uuid.UUID:
    return create_event(
        context.db,
        creator_id,
        title,
        (tag_id,),
        latitude=point[0],
        longitude=point[1],
        # The real point: these tests are about distance, not the offset.
        approx_point=kwargs.pop("approx_point", point),
        **kwargs,
    )


def test_feed_near_the_viewer_keeps_nearby_cities_and_drops_far_ones(
    context: FeedContext,
) -> None:
    creator_id, sports = sports_interest(context)
    create_event_at(context, creator_id, sports, "Pelada no Parcão", PORTO_ALEGRE)
    create_event_at(context, creator_id, sports, "Corrida em Canoas", CANOAS)
    create_event_at(context, creator_id, sports, "Vôlei em Gravataí", GRAVATAI)
    create_event_at(context, creator_id, sports, "Futebol na Paulista", SAO_PAULO)

    assert set(titles_by_tag(feed_near(context, PORTO_ALEGRE))["Esportes"]) == {
        "Pelada no Parcão",
        "Corrida em Canoas",
        "Vôlei em Gravataí",
    }


def test_feed_without_coordinates_is_not_bounded_by_distance(
    context: FeedContext,
) -> None:
    creator_id, sports = sports_interest(context)
    create_event_at(context, creator_id, sports, "Pelada no Parcão", PORTO_ALEGRE)
    create_event_at(context, creator_id, sports, "Futebol na Paulista", SAO_PAULO)

    # Older app versions send no position and keep getting the whole feed.
    assert set(titles_by_tag(get_feed(context))["Esportes"]) == {
        "Pelada no Parcão",
        "Futebol na Paulista",
    }


def test_feed_radius_is_a_circle_with_a_configurable_size(
    context: FeedContext,
) -> None:
    creator_id, sports = sports_interest(context)
    origin_latitude, origin_longitude = PORTO_ALEGRE
    # Due north: 0.85° ≈ 94.6 km and 0.95° ≈ 105.8 km of latitude.
    create_event_at(
        context,
        creator_id,
        sports,
        "A 95 km",
        (origin_latitude + 0.85, origin_longitude),
        starts_at=NOW + timedelta(days=1),
    )
    create_event_at(
        context,
        creator_id,
        sports,
        "A 106 km",
        (origin_latitude + 0.95, origin_longitude),
        starts_at=NOW + timedelta(days=2),
    )
    # Inside the 100 km bounding square but ~126 km away, past its circle.
    create_event_at(
        context,
        creator_id,
        sports,
        "No canto do quadrado",
        (
            origin_latitude + 0.8,
            origin_longitude + 0.8 / math.cos(math.radians(origin_latitude)),
        ),
        starts_at=NOW + timedelta(days=3),
    )

    assert titles_by_tag(feed_near(context, PORTO_ALEGRE)) == {"Esportes": ["A 95 km"]}
    assert titles_by_tag(feed_near(context, PORTO_ALEGRE, radius_km=110)) == {
        "Esportes": ["A 95 km", "A 106 km"]
    }
    assert titles_by_tag(feed_near(context, PORTO_ALEGRE, radius_km=130)) == {
        "Esportes": ["A 95 km", "A 106 km", "No canto do quadrado"]
    }


def test_feed_radius_crosses_the_antimeridian(context: FeedContext) -> None:
    creator_id, sports = sports_interest(context)
    # ~22 km apart across longitude ±180.
    create_event_at(context, creator_id, sports, "Do outro lado", (0.0, -179.9))
    create_event_at(context, creator_id, sports, "Longe", (0.0, -170.0))

    assert titles_by_tag(feed_near(context, (0.0, 179.9))) == {
        "Esportes": ["Do outro lado"]
    }


def test_feed_measures_the_distance_from_the_event_approximate_point(
    context: FeedContext,
) -> None:
    creator_id, sports = sports_interest(context)
    # The real address is next to the viewer, the approximate point is not:
    # the radius must not reveal more than the approximate point already does.
    create_event_at(
        context,
        creator_id,
        sports,
        "Endereço perto, ponto longe",
        PORTO_ALEGRE,
        approx_point=SAO_PAULO,
    )
    create_event_at(
        context,
        creator_id,
        sports,
        "Endereço longe, ponto perto",
        SAO_PAULO,
        approx_point=CANOAS,
    )

    assert titles_by_tag(feed_near(context, PORTO_ALEGRE)) == {
        "Esportes": ["Endereço longe, ponto perto"]
    }


def test_feed_paginates_only_among_the_events_within_the_radius(
    context: FeedContext,
) -> None:
    creator_id, sports = sports_interest(context)
    # The far events come first by date, so a filter applied after the page
    # was cut would leave the section empty or flag a next page wrongly.
    create_event_at(
        context,
        creator_id,
        sports,
        "Longe 1",
        SAO_PAULO,
        starts_at=NOW + timedelta(days=1),
    )
    create_event_at(
        context,
        creator_id,
        sports,
        "Longe 2",
        SAO_PAULO,
        starts_at=NOW + timedelta(days=2),
    )
    create_event_at(
        context,
        creator_id,
        sports,
        "Perto",
        CANOAS,
        starts_at=NOW + timedelta(days=3),
    )

    payload = feed_near(context, PORTO_ALEGRE, limit=1)

    assert titles_by_tag(payload) == {"Esportes": ["Perto"]}
    assert payload["sections"][0]["has_more"] is False


@pytest.mark.parametrize(
    "params",
    [
        {"latitude": -30.0},
        {"longitude": -51.0},
        {"latitude": -90.1, "longitude": -51.0},
        {"latitude": 90.1, "longitude": -51.0},
        {"latitude": -30.0, "longitude": -180.1},
        {"latitude": -30.0, "longitude": 180.1},
    ],
)
def test_feed_rejects_incomplete_or_out_of_range_coordinates(
    context: FeedContext, params: dict[str, float]
) -> None:
    response = context.client.get("/feed", params=params, headers=context.auth_headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid coordinates"}


@pytest.mark.parametrize("radius_km", [0, 501])
def test_feed_rejects_a_radius_outside_the_accepted_range(
    context: FeedContext, radius_km: int
) -> None:
    response = context.client.get(
        "/feed",
        params={"latitude": -30.0, "longitude": -51.0, "radius_km": radius_km},
        headers=context.auth_headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid radius"}


@pytest.mark.parametrize("radius_km", [1, 500])
def test_feed_accepts_the_radius_boundaries(
    context: FeedContext, radius_km: int
) -> None:
    creator_id, sports = sports_interest(context)
    create_event_at(context, creator_id, sports, "Pelada no Parcão", PORTO_ALEGRE)

    assert titles_by_tag(feed_near(context, PORTO_ALEGRE, radius_km=radius_km)) == {
        "Esportes": ["Pelada no Parcão"]
    }
