import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.domain.entities import SearchFilters, SearchQuery
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    SearchResultType,
    UserRoleEnum,
    UserTypeEnum,
)
from app.domain.services import SearchService, visible_events_query
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    BusinessProfileModel,
    EventModel,
    EventParticipantModel,
    PersonProfileModel,
    TagModel,
    UserBlockModel,
    UserModel,
    event_tag,
    user_tag,
)
from app.infrastructure.repository.search import SqlAlchemySearchRepository
from app.main import app

USER_EMAIL = "searcher@hangy.com"
NOW = datetime.now(UTC)


@dataclass(frozen=True)
class SearchContext:
    client: TestClient
    db: Session
    token: str
    user_id: UUID

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def context() -> Iterator[SearchContext]:
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
        viewer_id = uuid.uuid4()
        db.add(
            UserModel(
                user_id=viewer_id,
                user_type=UserTypeEnum.PERSONAL,
                role=UserRoleEnum.USER,
                email=USER_EMAIL,
                password_hash="hashed",
                name="Visitante Busca",
            )
        )
        db.commit()
        token = jwt.encode(
            {
                "sub": str(viewer_id),
                "exp": datetime.now(UTC) + timedelta(minutes=15),
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        yield SearchContext(
            client=client,
            db=db,
            token=token,
            user_id=viewer_id,
        )
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_person(
    db: Session,
    name: str,
    *,
    user_id: UUID | None = None,
    city: str = "Porto Alegre",
    state: str = "RS",
) -> UUID:
    uid = user_id or uuid.uuid4()
    user = UserModel(
        user_id=uid,
        user_type=UserTypeEnum.PERSONAL,
        role=UserRoleEnum.USER,
        email=f"{uid}@hangy.test",
        password_hash="hashed",
        name=name,
        description=f"Bio de {name}",
    )
    profile = PersonProfileModel(
        user_id=uid,
        cpf=str(uid.int)[:11],
        date_of_birth=NOW.date(),
        state=state,
        city=city,
    )
    db.add_all([user, profile])
    db.commit()
    return uid


def create_business(
    db: Session,
    business_name: str,
    *,
    user_id: UUID | None = None,
    address: str = "Av. Osvaldo Aranha, 100",
) -> UUID:
    uid = user_id or uuid.uuid4()
    user = UserModel(
        user_id=uid,
        user_type=UserTypeEnum.BUSINESS,
        role=UserRoleEnum.USER,
        email=f"{uid}@hangy.test",
        password_hash="hashed",
        name=business_name,
        description=f"Descrição de {business_name}",
    )
    profile = BusinessProfileModel(
        user_id=uid,
        cnpj=str(uid.int)[:14],
        address=address,
        business_latitude=-30.0,
        business_longitude=-51.0,
    )
    db.add_all([user, profile])
    db.commit()
    return uid


def create_tag(
    db: Session,
    name: str,
    parent_id: UUID | None = None,
) -> UUID:
    tag = TagModel(tag_name=name, tag_parent_id=parent_id)
    db.add(tag)
    db.commit()
    return tag.tag_id


def add_interest(db: Session, user_id: UUID, tag_id: UUID) -> None:
    db.execute(user_tag.insert().values(user_id=user_id, tag_id=tag_id))
    db.commit()


def create_event(
    db: Session,
    creator_id: UUID,
    title: str,
    *,
    event_id: UUID | None = None,
    description: str | None = "Pelada de sábado, traga a chuteira.",
    tag_ids: tuple[UUID, ...] = (),
    starts_at: datetime | None = None,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    event_status: EventStatusEnum = EventStatusEnum.PUBLISHED,
    location_name: str | None = "Parcão",
    neighborhood: str | None = "Moinhos de Vento",
    city: str | None = "Porto Alegre",
    latitude: float = -30.0,
    longitude: float = -51.0,
) -> UUID:
    effective_starts = starts_at if starts_at is not None else NOW + timedelta(days=2)
    event = EventModel(
        event_id=event_id or uuid.uuid4(),
        event_creator_id=creator_id,
        event_title=title,
        event_description=description,
        location_name=location_name,
        location_neighborhood=neighborhood,
        location_city=city,
        event_latitude=latitude,
        event_longitude=longitude,
        starts_at=effective_starts,
        ends_at=effective_starts + timedelta(hours=2),
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
    event_id: UUID,
    user_id: UUID,
    status: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> None:
    db.add(EventParticipantModel(event_id=event_id, user_id=user_id, status=status))
    db.commit()


# ============================================================================
# US10.1 — Busca textual
# ============================================================================


def test_search_returns_all_three_blocks_with_own_counts_and_preview_limit(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Organizador")
    for idx in range(3):
        create_event(
            context.db,
            creator_id,
            f"Futebol {idx}",
            starts_at=NOW + timedelta(days=idx + 1),
        )
    create_business(context.db, "Arena Futebol Sul")
    create_business(context.db, "Quadra Futebol Norte")
    create_person(context.db, "Carlos Futebol")

    response = context.client.get(
        "/search",
        params={"q": "futebol", "preview": 2},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "futebol"
    assert body["events"]["total"] == 3
    assert body["events"]["has_more"] is True
    assert [item["title"] for item in body["events"]["items"]] == [
        "Futebol 0",
        "Futebol 1",
    ]
    assert body["businesses"]["total"] == 2
    assert body["businesses"]["has_more"] is False
    assert [item["business_name"] for item in body["businesses"]["items"]] == [
        "Arena Futebol Sul",
        "Quadra Futebol Norte",
    ]
    assert body["users"]["total"] == 1
    assert body["users"]["has_more"] is False
    assert [item["name"] for item in body["users"]["items"]] == ["Carlos Futebol"]


def test_search_orders_results_independently_of_uuid_order(
    context: SearchContext,
) -> None:
    # Higher UUID has earlier starts_at / earlier alphabetical name to prove
    # ordering is not an accident of primary key order.
    high_uuid_1 = UUID("ffffffff-0000-4000-8000-000000000001")
    low_uuid_1 = UUID("00000001-0000-4000-8000-000000000001")
    high_uuid_2 = UUID("ffffffff-0000-4000-8000-000000000002")
    low_uuid_2 = UUID("00000001-0000-4000-8000-000000000002")

    p_first = create_person(context.db, "Ana Corrida", user_id=high_uuid_1)
    create_person(context.db, "Zeca Corrida", user_id=low_uuid_1)

    create_event(
        context.db,
        p_first,
        "Corrida Tarde",
        event_id=low_uuid_2,
        starts_at=NOW + timedelta(days=3),
    )
    create_event(
        context.db,
        p_first,
        "Corrida Cedo",
        event_id=high_uuid_2,
        starts_at=NOW + timedelta(days=1),
    )

    response = context.client.get(
        "/search",
        params={"q": "corrida"},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["events"]["items"]] == [
        "Corrida Cedo",
        "Corrida Tarde",
    ]
    assert [item["name"] for item in body["users"]["items"]] == [
        "Ana Corrida",
        "Zeca Corrida",
    ]


@pytest.mark.parametrize("query_param", [{"q": "a"}, {"q": " x "}, {"q": ""}, {}])
def test_search_rejects_short_or_missing_query_without_filters(
    context: SearchContext,
    query_param: dict[str, str],
) -> None:
    response = context.client.get(
        "/search",
        params=query_param,
        headers=context.auth_headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Query is too short"}


def test_search_excludes_blocked_users_and_blockers_from_people_and_businesses(
    context: SearchContext,
) -> None:
    blocked_person = create_person(context.db, "Pedro Bloqueado")
    blocker_person = create_person(context.db, "Pedro Bloqueador")
    visible_person = create_person(context.db, "Pedro Visível")
    blocked_business = create_business(context.db, "Bar do Pedro Bloqueado")
    visible_business = create_business(context.db, "Bar do Pedro Visível")

    context.db.add_all(
        [
            UserBlockModel(blocker_id=context.user_id, blocked_id=blocked_person),
            UserBlockModel(blocker_id=blocker_person, blocked_id=context.user_id),
            UserBlockModel(blocker_id=context.user_id, blocked_id=blocked_business),
        ]
    )
    context.db.commit()

    response = context.client.get(
        "/search",
        params={"q": "pedro"},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [u["user_id"] for u in body["users"]["items"]] == [str(visible_person)]
    assert body["users"]["total"] == 1
    assert [b["user_id"] for b in body["businesses"]["items"]] == [
        str(visible_business)
    ]
    assert body["businesses"]["total"] == 1


def test_search_hides_past_and_non_published_events(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Organizador")
    create_event(
        context.db,
        creator_id,
        "Vôlei ontem",
        starts_at=NOW - timedelta(days=1),
    )
    create_event(
        context.db,
        creator_id,
        "Vôlei agora",
        starts_at=NOW - timedelta(seconds=1),
    )
    create_event(
        context.db,
        creator_id,
        "Vôlei rascunho",
        event_status=EventStatusEnum.DRAFT,
    )
    create_event(
        context.db,
        creator_id,
        "Vôlei cancelado",
        event_status=EventStatusEnum.CANCELLED,
    )
    create_event(
        context.db,
        creator_id,
        "Vôlei encerrado",
        event_status=EventStatusEnum.FINISHED,
    )
    future_id = create_event(
        context.db,
        creator_id,
        "Vôlei amanhã",
        starts_at=NOW + timedelta(days=1),
    )

    response = context.client.get(
        "/search",
        params={"q": "volei"},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["event_id"] for item in body["events"]["items"]] == [str(future_id)]
    assert body["events"]["total"] == 1


@pytest.mark.parametrize(
    "term",
    ["parcao", "PARCÃO", "Parcão", "PARCAO", "pArCãO"],
)
def test_search_is_case_insensitive_and_accent_insensitive(
    context: SearchContext,
    term: str,
) -> None:
    creator_id = create_person(context.db, "João Parcão")
    create_business(context.db, "Café do Parcão")
    create_event(context.db, creator_id, "Pelada no Parcão")

    response = context.client.get(
        "/search",
        params={"q": term},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["title"] for item in body["events"]["items"]] == ["Pelada no Parcão"]
    assert [item["business_name"] for item in body["businesses"]["items"]] == [
        "Café do Parcão"
    ]
    assert [item["name"] for item in body["users"]["items"]] == ["João Parcão"]


def test_search_explain_shows_text_index_usage(context: SearchContext) -> None:
    creator_id = create_person(context.db, "Organizador")
    create_event(context.db, creator_id, "Pelada no Parcão")

    repo = SqlAlchemySearchRepository(context.db)
    plan_lines = repo.explain_event_search_query(context.user_id, "futebol")
    joined_plan = "\n".join(plan_lines)

    assert "idx_event_title_trgm" in joined_plan


# ============================================================================
# US10.2 — Filtros de busca por tags e data
# ============================================================================


def test_search_filter_by_single_tag_restricts_events(context: SearchContext) -> None:
    creator_id = create_person(context.db, "Organizador")
    football = create_tag(context.db, "Futebol")
    music = create_tag(context.db, "Música")
    create_event(context.db, creator_id, "Encontro Esportivo", tag_ids=(football,))
    create_event(context.db, creator_id, "Encontro Musical", tag_ids=(music,))

    response = context.client.get(
        "/search",
        params={"q": "encontro", "tag_ids": str(football)},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["events"]["items"]] == [
        "Encontro Esportivo"
    ]


def test_search_filter_by_two_tags_returns_union(context: SearchContext) -> None:
    creator_id = create_person(context.db, "Organizador")
    football = create_tag(context.db, "Futebol")
    volleyball = create_tag(context.db, "Vôlei")
    chess = create_tag(context.db, "Xadrez")

    create_event(
        context.db,
        creator_id,
        "Torneio A",
        tag_ids=(football,),
        starts_at=NOW + timedelta(days=1),
    )
    create_event(
        context.db,
        creator_id,
        "Torneio B",
        tag_ids=(volleyball,),
        starts_at=NOW + timedelta(days=2),
    )
    create_event(
        context.db,
        creator_id,
        "Torneio C",
        tag_ids=(chess,),
        starts_at=NOW + timedelta(days=3),
    )

    response = context.client.get(
        "/search",
        params={"q": "torneio", "tag_ids": f"{football},{volleyball}"},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["events"]["items"]] == [
        "Torneio A",
        "Torneio B",
    ]


def test_search_filter_by_macro_tag_includes_micro_children_events(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Organizador")
    sports = create_tag(context.db, "Esportes")
    football = create_tag(context.db, "Futebol", parent_id=sports)
    futsal = create_tag(context.db, "Futsal", parent_id=football)
    music = create_tag(context.db, "Música")

    create_event(
        context.db,
        creator_id,
        "Copa Campo",
        tag_ids=(football,),
        starts_at=NOW + timedelta(days=1),
    )
    create_event(
        context.db,
        creator_id,
        "Copa Quadra",
        tag_ids=(futsal,),
        starts_at=NOW + timedelta(days=2),
    )
    create_event(
        context.db,
        creator_id,
        "Copa Bandas",
        tag_ids=(music,),
        starts_at=NOW + timedelta(days=3),
    )

    response = context.client.get(
        "/search",
        params={"q": "copa", "tag_ids": str(sports)},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["events"]["items"]] == [
        "Copa Campo",
        "Copa Quadra",
    ]


def test_search_filter_by_date_range_slices_events_correctly(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Organizador")
    day_before = (NOW + timedelta(days=2)).date()
    day_in_start = (NOW + timedelta(days=5)).date()
    day_in_end = (NOW + timedelta(days=7)).date()
    day_after = (NOW + timedelta(days=10)).date()

    create_event(
        context.db,
        creator_id,
        "Festival Antes",
        starts_at=datetime(
            day_before.year, day_before.month, day_before.day, 23, 59, tzinfo=UTC
        ),
    )
    create_event(
        context.db,
        creator_id,
        "Festival Início",
        starts_at=datetime(
            day_in_start.year, day_in_start.month, day_in_start.day, 0, 0, tzinfo=UTC
        ),
    )
    create_event(
        context.db,
        creator_id,
        "Festival Fim",
        starts_at=datetime(
            day_in_end.year, day_in_end.month, day_in_end.day, 23, 59, tzinfo=UTC
        ),
    )
    create_event(
        context.db,
        creator_id,
        "Festival Depois",
        starts_at=datetime(
            day_after.year, day_after.month, day_after.day, 0, 0, tzinfo=UTC
        ),
    )

    response = context.client.get(
        "/search",
        params={
            "q": "festival",
            "date_from": day_in_start.isoformat(),
            "date_to": day_in_end.isoformat(),
        },
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()["events"]["items"]] == [
        "Festival Início",
        "Festival Fim",
    ]


def test_search_inverted_date_range_returns_400(context: SearchContext) -> None:
    response = context.client.get(
        "/search",
        params={
            "q": "futebol",
            "date_from": "2026-09-10",
            "date_to": "2026-09-01",
        },
        headers=context.auth_headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "date_from must be before date_to"}


@pytest.mark.parametrize(
    ("param_name", "bad_value"),
    [
        ("date_from", "01/09/2026"),
        ("date_to", "2026-13-40"),
        ("date_from", "2026-09-01T10:00:00"),
        ("date_to", "not-a-date"),
    ],
)
def test_search_invalid_date_format_returns_400(
    context: SearchContext,
    param_name: str,
    bad_value: str,
) -> None:
    response = context.client.get(
        "/search",
        params={"q": "futebol", param_name: bad_value},
        headers=context.auth_headers,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid date format"}


@pytest.mark.parametrize("bad_tag_id", [str(uuid.uuid4()), "not-a-uuid"])
def test_search_nonexistent_tag_id_returns_404(
    context: SearchContext,
    bad_tag_id: str,
) -> None:
    response = context.client.get(
        "/search",
        params={"q": "futebol", "tag_ids": bad_tag_id},
        headers=context.auth_headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Tag not found"}


def test_search_filters_do_not_affect_businesses_or_users_blocks(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Lucas Samba")
    create_business(context.db, "Casa do Samba")
    music = create_tag(context.db, "Música")
    sports = create_tag(context.db, "Esportes")
    create_event(context.db, creator_id, "Roda de Samba", tag_ids=(music,))

    response = context.client.get(
        "/search",
        params={
            "q": "samba",
            "tag_ids": str(sports),
            "date_from": "2099-01-01",
            "date_to": "2099-01-02",
        },
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["events"]["items"] == []
    assert body["events"]["total"] == 0
    assert [b["business_name"] for b in body["businesses"]["items"]] == [
        "Casa do Samba"
    ]
    assert [u["name"] for u in body["users"]["items"]] == ["Lucas Samba"]


def test_search_without_query_but_with_filters_works_and_returns_applied_filters(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Organizador")
    football = create_tag(context.db, "Futebol")
    target_date = (NOW + timedelta(days=4)).date()
    event_id = create_event(
        context.db,
        creator_id,
        "Pelada Sem Termo",
        tag_ids=(football,),
        starts_at=datetime(
            target_date.year, target_date.month, target_date.day, 19, 0, tzinfo=UTC
        ),
    )

    response = context.client.get(
        "/search",
        params={
            "tag_ids": str(football),
            "date_from": target_date.isoformat(),
            "date_to": target_date.isoformat(),
        },
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] is None
    assert body["applied_filters"] == {
        "tag_ids": [str(football)],
        "date_from": target_date.isoformat(),
        "date_to": target_date.isoformat(),
    }
    assert [item["event_id"] for item in body["events"]["items"]] == [str(event_id)]
    assert body["businesses"] == {"items": [], "total": 0, "has_more": False}
    assert body["users"] == {"items": [], "total": 0, "has_more": False}


# ============================================================================
# US10.3 — Exibição de eventos privados na listagem
# ============================================================================


def test_private_event_appears_in_preview_with_approximate_location_for_non_participant(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Ana")
    other_id = create_person(context.db, "Convidado Confirmado")
    event_id = create_event(
        context.db,
        creator_id,
        "Aniversário da Ana",
        description="Festa surpresa no salão de festas, apto 402.",
        privacy=EventPrivacyEnum.PRIVATE,
        location_name="Rua secreta, 402",
        neighborhood="Bom Fim",
        city="Porto Alegre",
    )
    add_participant(context.db, event_id, other_id)

    response = context.client.get(
        "/search",
        params={"q": "aniversario"},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    [item] = response.json()["events"]["items"]
    assert item["event_id"] == str(event_id)
    assert item["title"] == "Aniversário da Ana"
    assert item["privacy"] == "PRIVATE"
    assert item["is_preview"] is True
    assert item["description"] is None
    assert item["participants_count"] is None
    assert item["location_name"] == "Bom Fim, Porto Alegre"
    assert item["location_precision"] == "APPROXIMATE"
    assert "Rua secreta" not in response.text


def test_private_event_appears_complete_for_confirmed_participant_and_organizer(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Ana")
    participant_event_id = create_event(
        context.db,
        creator_id,
        "Jantar Secreto Participante",
        description="Traga vinho tinto.",
        privacy=EventPrivacyEnum.PRIVATE,
        location_name="Rua da Ana, 100",
        neighborhood="Bom Fim",
        city="Porto Alegre",
        starts_at=NOW + timedelta(days=1),
    )
    add_participant(context.db, participant_event_id, context.user_id)

    organizer_event_id = create_event(
        context.db,
        context.user_id,
        "Jantar Secreto Organizador",
        description="Meu próprio jantar.",
        privacy=EventPrivacyEnum.PRIVATE,
        location_name="Minha Casa, 200",
        neighborhood="Centro",
        city="Porto Alegre",
        starts_at=NOW + timedelta(days=2),
    )

    response = context.client.get(
        "/search",
        params={"q": "jantar secreto"},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    items = response.json()["events"]["items"]
    assert len(items) == 2

    assert items[0]["event_id"] == str(participant_event_id)
    assert items[0]["is_preview"] is False
    assert items[0]["description"] == "Traga vinho tinto."
    assert items[0]["participants_count"] == 1
    assert items[0]["location_name"] == "Rua da Ana, 100"
    assert items[0]["location_precision"] == "EXACT"

    assert items[1]["event_id"] == str(organizer_event_id)
    assert items[1]["is_preview"] is False
    assert items[1]["description"] == "Meu próprio jantar."
    assert items[1]["participants_count"] == 0
    assert items[1]["location_name"] == "Minha Casa, 200"
    assert items[1]["location_precision"] == "EXACT"


def test_invite_only_event_hidden_for_uninvited_and_visible_for_invited(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Organizador")
    uninvited_event = create_event(
        context.db,
        creator_id,
        "Churrasco Fechado Não Convidado",
        privacy=EventPrivacyEnum.INVITE_ONLY,
    )
    invited_event = create_event(
        context.db,
        creator_id,
        "Churrasco Fechado Convidado",
        description="Só para quem recebeu o link.",
        privacy=EventPrivacyEnum.INVITE_ONLY,
        location_name="Sítio Verde",
    )
    add_participant(context.db, invited_event, context.user_id)

    response = context.client.get(
        "/search",
        params={"q": "churrasco fechado"},
        headers=context.auth_headers,
    )

    assert response.status_code == 200
    items = response.json()["events"]["items"]
    assert [item["event_id"] for item in items] == [str(invited_event)]
    assert str(uninvited_event) not in {item["event_id"] for item in items}
    assert items[0]["is_preview"] is False
    assert items[0]["description"] == "Só para quem recebeu o link."
    assert items[0]["location_name"] == "Sítio Verde"
    assert items[0]["location_precision"] == "EXACT"
    assert items[0]["participants_count"] == 1


def test_same_visibility_rule_applies_across_search_feed_and_nearby(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Organizador")
    blocker_id = create_person(context.db, "Bloqueador")
    sports = create_tag(context.db, "Esportes")
    add_interest(context.db, context.user_id, sports)

    context.db.add(UserBlockModel(blocker_id=blocker_id, blocked_id=context.user_id))
    context.db.commit()

    public_id = create_event(
        context.db,
        creator_id,
        "Trilha Pública",
        tag_ids=(sports,),
        privacy=EventPrivacyEnum.PUBLIC,
        location_name="Morro Santana",
        latitude=-30.0,
        longitude=-51.0,
        starts_at=NOW + timedelta(days=1),
    )
    private_id = create_event(
        context.db,
        creator_id,
        "Trilha Privada",
        tag_ids=(sports,),
        privacy=EventPrivacyEnum.PRIVATE,
        location_name="Endereço Secreto, 999",
        neighborhood="Três Figueiras",
        city="Porto Alegre",
        latitude=-30.0,
        longitude=-51.0,
        starts_at=NOW + timedelta(days=2),
    )
    invite_only_id = create_event(
        context.db,
        creator_id,
        "Trilha Por Convite",
        tag_ids=(sports,),
        privacy=EventPrivacyEnum.INVITE_ONLY,
        latitude=-30.0,
        longitude=-51.0,
        starts_at=NOW + timedelta(days=3),
    )
    blocked_id = create_event(
        context.db,
        blocker_id,
        "Trilha Bloqueada",
        tag_ids=(sports,),
        privacy=EventPrivacyEnum.PUBLIC,
        latitude=-30.0,
        longitude=-51.0,
        starts_at=NOW + timedelta(days=4),
    )

    search_resp = context.client.get(
        "/search",
        params={"q": "trilha"},
        headers=context.auth_headers,
    )
    feed_resp = context.client.get("/feed", headers=context.auth_headers)
    nearby_resp = context.client.get(
        "/events/nearby",
        params={"latitude": -30.0, "longitude": -51.0, "radius_m": 5_000},
        headers=context.auth_headers,
    )

    assert search_resp.status_code == 200
    assert feed_resp.status_code == 200
    assert nearby_resp.status_code == 200

    search_items = {
        item["event_id"]: item for item in search_resp.json()["events"]["items"]
    }
    feed_items = {
        item["event_id"]: item
        for section in feed_resp.json()["sections"]
        for item in section["items"]
    }
    nearby_items = {item["event_id"]: item for item in nearby_resp.json()["items"]}

    expected_ids = {str(public_id), str(private_id)}
    assert set(search_items) == expected_ids
    assert set(feed_items) == expected_ids
    assert set(nearby_items) == expected_ids
    assert str(invite_only_id) not in search_items
    assert str(blocked_id) not in search_items

    for endpoint_items in (search_items, feed_items, nearby_items):
        pub = endpoint_items[str(public_id)]
        priv = endpoint_items[str(private_id)]
        assert pub["location_precision"] == "EXACT"
        assert pub["location_name"] == "Morro Santana"
        assert priv["location_precision"] == "APPROXIMATE"
        assert priv["location_name"] == "Três Figueiras, Porto Alegre"

    # Also verify the shared `visible_events_query(user_id)` helper directly.
    visible_events = context.db.scalars(
        visible_events_query(context.user_id, reference_time=NOW)
    ).all()
    assert {e.event_id for e in visible_events} == {public_id, private_id}


def test_search_requires_authentication(context: SearchContext) -> None:
    response = context.client.get("/search", params={"q": "futebol"})
    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_search_rejects_preview_limit_out_of_bounds(context: SearchContext) -> None:
    for bad_preview in (0, 51):
        response = context.client.get(
            "/search",
            params={"q": "futebol", "preview": bad_preview},
            headers=context.auth_headers,
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid pagination parameters"}


def test_search_service_supports_type_and_offset_parameterization(
    context: SearchContext,
) -> None:
    creator_id = create_person(context.db, "Organizador")
    for idx in range(3):
        create_event(
            context.db,
            creator_id,
            f"Basquete {idx}",
            starts_at=NOW + timedelta(days=idx + 1),
        )
    create_business(context.db, "Quadra Basquete")

    service = SearchService(SqlAlchemySearchRepository(context.db))
    result = service.search(
        SearchQuery(
            viewer_id=context.user_id,
            query="basquete",
            preview_limit=1,
            offset=1,
            result_type=SearchResultType.EVENT,
            filters=SearchFilters(),
        )
    )

    assert [item.title for item in result.events.items] == ["Basquete 1"]
    assert result.events.total == 3
    assert result.events.has_more is True
    assert result.businesses.items == ()
    assert result.users.items == ()
