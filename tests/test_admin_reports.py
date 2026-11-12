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
    EventPrivacyEnum,
    EventStatusEnum,
    ReportStatusEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel
from app.main import app
from tests.report_helpers import free_report_type

NOW = datetime.now(UTC)
QueueClient = tuple[TestClient, sessionmaker[Session]]


@pytest.fixture
def queue_client() -> Iterator[QueueClient]:
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
    name: str,
    role: UserRoleEnum = UserRoleEnum.USER,
    user_type: UserTypeEnum = UserTypeEnum.PERSONAL,
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
        )
    )
    db.commit()
    return user_id


def add_event(db: Session, creator_id: UUID, title: str) -> UUID:
    event_id = uuid4()
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=creator_id,
            event_title=title,
            event_latitude=-30.0,
            event_longitude=-51.0,
            starts_at=NOW + timedelta(days=1),
            ends_at=NOW + timedelta(days=1, hours=2),
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=EventPrivacyEnum.PUBLIC,
        )
    )
    db.commit()
    return event_id


def add_report(
    db: Session,
    creator_id: UUID,
    *,
    number: int,
    minutes_ago: int,
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
    user_id: UUID | None = None,
    event_id: UUID | None = None,
) -> None:
    report_type = free_report_type(
        db, creator_id, reported_user_id=user_id, reported_event_id=event_id
    )
    db.add(
        ReportModel(
            report_id=uuid4(),
            report_number=number,
            report_creator_id=creator_id,
            reported_user_id=user_id,
            reported_event_id=event_id,
            report_type=report_type,
            description="Mensagens ofensivas",
            status=status,
            created_at=NOW - timedelta(minutes=minutes_ago),
            updated_at=NOW - timedelta(minutes=minutes_ago),
        )
    )
    db.commit()


def build_queue(db: Session) -> UUID:
    admin_id = add_user(db, "Admin", role=UserRoleEnum.ADMIN)
    creator_id = add_user(db, "Denunciante")
    lucas_id = add_user(db, "Lucas Ferreira")
    bar_id = add_user(db, "Bar do Zé", user_type=UserTypeEnum.BUSINESS)
    ana_id = add_user(db, "Ana Souza")
    event_id = add_event(db, creator_id, "Pelada no Parcão")
    add_report(db, creator_id, number=1, minutes_ago=10, user_id=lucas_id)
    add_report(
        db,
        creator_id,
        number=2,
        minutes_ago=5,
        status=ReportStatusEnum.REVIEWED,
        user_id=lucas_id,
    )
    add_report(db, creator_id, number=3, minutes_ago=1, user_id=bar_id)
    add_report(
        db,
        creator_id,
        number=4,
        minutes_ago=20,
        status=ReportStatusEnum.RESOLVED,
        event_id=event_id,
    )
    add_report(
        db,
        creator_id,
        number=5,
        minutes_ago=2,
        status=ReportStatusEnum.REJECTED,
        user_id=ana_id,
    )
    return admin_id


def get_queue(client: TestClient, admin_id: UUID, **params: str | int) -> dict:
    response = client.get("/admin/reports", params=params, headers=header_for(admin_id))
    assert response.status_code == 200, response.text
    return response.json()


def numbers(payload: dict) -> list[int]:
    return [item["report_number"] for item in payload["items"]]


def test_lists_the_queue_grouped_by_target_newest_first(
    queue_client: QueueClient,
) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id = build_queue(db)

    payload = get_queue(client, admin_id)

    assert [item["target_name"] for item in payload["items"]] == [
        "Bar do Zé",
        "Lucas Ferreira",
        "Pelada no Parcão",
    ]
    assert [item["target_type"] for item in payload["items"]] == [
        "BUSINESS",
        "USER",
        "EVENT",
    ]
    assert [item["report_count"] for item in payload["items"]] == [1, 2, 1]
    assert numbers(payload) == [3, 2, 4]
    assert payload["items"][0]["reason"] == "HARASSMENT"
    assert payload["next_cursor"] is None


def test_filters_by_status(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id = build_queue(db)

    pending = get_queue(client, admin_id, status="PENDING")
    rejected = get_queue(client, admin_id, status="REJECTED")

    assert numbers(pending) == [3, 1]
    assert pending["items"][1]["report_count"] == 1
    assert numbers(rejected) == [5]


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("lucas", [2]),
        ("PELADA", [4]),
        ("bar", [3]),
        ("#3", [3]),
        ("2", [2]),
        ("zzz", []),
    ],
)
def test_search_matches_target_name_event_title_and_report_number(
    queue_client: QueueClient, term: str, expected: list[int]
) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id = build_queue(db)

    assert numbers(get_queue(client, admin_id, search=term)) == expected


def test_search_by_number_still_counts_the_whole_target(
    queue_client: QueueClient,
) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id = build_queue(db)

    payload = get_queue(client, admin_id, search="1")

    assert numbers(payload) == [2]
    assert payload["items"][0]["report_count"] == 2


def test_paginates_with_an_opaque_cursor(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id = build_queue(db)

    first = get_queue(client, admin_id, limit=1)
    second = get_queue(client, admin_id, limit=1, cursor=first["next_cursor"])
    third = get_queue(client, admin_id, limit=1, cursor=second["next_cursor"])

    assert numbers(first) == [3]
    assert first["next_cursor"] is not None
    assert numbers(second) == [2]
    assert numbers(third) == [4]
    assert third["next_cursor"] is None


def test_rejects_a_malformed_cursor(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id = build_queue(db)

    response = client.get(
        "/admin/reports",
        params={"cursor": "not-a-cursor"},
        headers=header_for(admin_id),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid pagination parameters"}


@pytest.mark.parametrize(
    "params", [{"status": "INVALID"}, {"limit": 0}, {"limit": 101}]
)
def test_rejects_invalid_query_params(
    queue_client: QueueClient, params: dict[str, str | int]
) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id = build_queue(db)

    response = client.get("/admin/reports", params=params, headers=header_for(admin_id))

    assert response.status_code == 422


def test_non_admin_gets_403(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        user_id = add_user(db, "Pessoa")

    response = client.get("/admin/reports", headers=header_for(user_id))

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}


def test_requires_authentication(queue_client: QueueClient) -> None:
    client, _ = queue_client

    response = client.get("/admin/reports")

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_status_change_keeps_opened_at_and_queue_order(
    queue_client: QueueClient,
) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id = add_user(db, "Admin", role=UserRoleEnum.ADMIN)
        creator_id = add_user(db, "Denunciante")
        older_id = add_user(db, "Alvo Antigo")
        newer_id = add_user(db, "Alvo Novo")
        add_report(db, creator_id, number=1, minutes_ago=60, user_id=older_id)
        add_report(db, creator_id, number=2, minutes_ago=10, user_id=newer_id)
    before = get_queue(client, admin_id)

    with session_factory() as db:
        report = db.scalars(select(ReportModel).filter_by(report_number=1)).one()
        report.status = ReportStatusEnum.REVIEWED
        db.commit()
    after = get_queue(client, admin_id)

    assert numbers(after) == numbers(before) == [2, 1]
    assert after["items"][1]["opened_at"] == before["items"][1]["opened_at"]


def build_target_queue(db: Session) -> tuple[UUID, UUID, UUID]:
    admin_id = add_user(db, "Admin", role=UserRoleEnum.ADMIN)
    creator_id = add_user(db, "Denunciante")
    lucas_id = add_user(db, "Lucas Ferreira")
    ana_id = add_user(db, "Ana Souza")
    event_id = add_event(db, lucas_id, "Pelada no Parcão")
    add_report(db, creator_id, number=1, minutes_ago=10, user_id=lucas_id)
    add_report(
        db,
        creator_id,
        number=2,
        minutes_ago=5,
        status=ReportStatusEnum.REVIEWED,
        user_id=lucas_id,
    )
    add_report(db, creator_id, number=3, minutes_ago=1, user_id=ana_id)
    add_report(db, creator_id, number=4, minutes_ago=20, event_id=event_id)
    return admin_id, lucas_id, event_id


def test_filters_by_target_user(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id, lucas_id, _ = build_target_queue(db)

    payload = get_queue(client, admin_id, target_user_id=str(lucas_id))

    assert numbers(payload) == [2]
    assert payload["items"][0]["target_name"] == "Lucas Ferreira"
    assert payload["items"][0]["report_count"] == 2


def test_filters_by_target_event(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id, _, event_id = build_target_queue(db)

    payload = get_queue(client, admin_id, target_event_id=str(event_id))

    assert numbers(payload) == [4]
    assert payload["items"][0]["target_type"] == "EVENT"
    assert payload["items"][0]["report_count"] == 1


def test_target_filter_combines_with_status(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id, lucas_id, _ = build_target_queue(db)

    payload = get_queue(
        client, admin_id, target_user_id=str(lucas_id), status="PENDING"
    )

    assert numbers(payload) == [1]
    assert payload["items"][0]["report_count"] == 1


def test_both_target_filters_return_400(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id, lucas_id, event_id = build_target_queue(db)

    response = client.get(
        "/admin/reports",
        params={"target_user_id": str(lucas_id), "target_event_id": str(event_id)},
        headers=header_for(admin_id),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Only one target filter is allowed"}


@pytest.mark.parametrize("param", ["target_user_id", "target_event_id"])
def test_unknown_target_returns_an_empty_list(
    queue_client: QueueClient, param: str
) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id, _, _ = build_target_queue(db)

    payload = get_queue(client, admin_id, **{param: str(uuid4())})

    assert payload == {"items": [], "next_cursor": None}


def test_invalid_target_id_returns_422(queue_client: QueueClient) -> None:
    client, session_factory = queue_client
    with session_factory() as db:
        admin_id, _, _ = build_target_queue(db)

    response = client.get(
        "/admin/reports",
        params={"target_user_id": "abc"},
        headers=header_for(admin_id),
    )

    assert response.status_code == 422
