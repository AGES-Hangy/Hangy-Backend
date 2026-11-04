from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.enums import (
    EventPrivacyEnum,
    EventStatusEnum,
    ReportStatusEnum,
    ReportTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    NotificationModel,
    ReportModel,
    UserBlockModel,
    UserConnectionModel,
    UserModel,
)
from app.main import app

USER_A_EMAIL = "ana@hangy.com"
USER_B_EMAIL = "bruno@hangy.com"
USER_C_EMAIL = "carla@hangy.com"
USER_PASSWORD = "strong-password"
NOW = datetime.now(UTC)


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


def db_session() -> Iterator[Session]:
    return app.dependency_overrides[get_db]()


def register_user(client: TestClient, email: str, cpf: str) -> UUID:
    response = client.post(
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": email,
            "password": USER_PASSWORD,
            "name": "Usuário de Teste",
            "cpf": cpf,
            "phone": "51999990000",
            "date_of_birth": "2000-04-12",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": "2026-08-01",
        },
    )
    assert response.status_code == 201
    return UUID(response.json()["user"]["id"])


def login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/auth/login", json={"email": email, "password": USER_PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_event(
    creator_id: UUID,
    *,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    event_status: EventStatusEnum = EventStatusEnum.PUBLISHED,
) -> UUID:
    db_generator = db_session()
    db = next(db_generator)
    try:
        event = EventModel(
            event_id=uuid4(),
            event_creator_id=creator_id,
            event_title="Churrasco",
            event_latitude=0.0,
            event_longitude=0.0,
            approx_latitude=0.0,
            approx_longitude=0.0,
            starts_at=NOW + timedelta(days=2),
            ends_at=NOW + timedelta(days=2, hours=2),
            event_status=event_status,
            event_privacy=privacy,
        )
        db.add(event)
        db.commit()
        return event.event_id
    finally:
        db_generator.close()


def query_scalar(statement):
    db_generator = db_session()
    db = next(db_generator)
    try:
        return db.scalar(statement)
    finally:
        db_generator.close()


@pytest.fixture
def users(client: TestClient) -> dict[str, UUID]:
    return {
        "a": register_user(client, USER_A_EMAIL, "52998224725"),
        "b": register_user(client, USER_B_EMAIL, "11144477735"),
        "c": register_user(client, USER_C_EMAIL, "39053344705"),
    }


def test_report_user_returns_201_without_exposing_the_author(
    client: TestClient, users: dict[str, UUID]
) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={
            "report_type": "HARASSMENT",
            "reported_user_id": str(users["b"]),
            "reported_event_id": None,
            "description": "Comentários ofensivos no evento",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"report_id", "report_type", "status", "created_at"}
    assert body["report_type"] == "HARASSMENT"
    assert body["status"] == "PENDING"
    assert body["created_at"]
    assert str(users["a"]) not in response.text

    report = query_scalar(select(ReportModel))
    assert report is not None
    assert str(report.report_id) == body["report_id"]
    assert report.report_creator_id == users["a"]
    assert report.reported_user_id == users["b"]
    assert report.reported_event_id is None
    assert report.status is ReportStatusEnum.PENDING
    assert report.description == "Comentários ofensivos no evento"
    assert report.created_at is not None


def test_report_event_returns_201(client: TestClient, users: dict[str, UUID]) -> None:
    event_id = create_event(users["b"])

    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={"report_type": "MISLEADING_EVENT", "reported_event_id": str(event_id)},
    )

    assert response.status_code == 201
    assert response.json()["report_type"] == "MISLEADING_EVENT"
    report = query_scalar(select(ReportModel))
    assert report.reported_event_id == event_id
    assert report.reported_user_id is None
    assert report.description == ""


def test_both_targets_returns_400(client: TestClient, users: dict[str, UUID]) -> None:
    event_id = create_event(users["b"])

    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={
            "report_type": "SPAM",
            "reported_user_id": str(users["b"]),
            "reported_event_id": str(event_id),
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Exactly one target is required"}
    assert query_scalar(select(func.count()).select_from(ReportModel)) == 0


def test_no_target_returns_400(client: TestClient, users: dict[str, UUID]) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={"report_type": "SPAM"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Exactly one target is required"}


def test_reason_outside_the_enum_returns_400(
    client: TestClient, users: dict[str, UUID]
) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={"report_type": "NOT_A_REASON", "reported_user_id": str(users["b"])},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid report reason"}


@pytest.mark.parametrize("report_type", [reason.value for reason in ReportTypeEnum])
def test_every_report_reason_is_accepted(
    client: TestClient, users: dict[str, UUID], report_type: str
) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={"report_type": report_type, "reported_user_id": str(users["b"])},
    )

    assert response.status_code == 201
    assert response.json()["report_type"] == report_type


def test_unknown_user_returns_404(client: TestClient, users: dict[str, UUID]) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={"report_type": "SPAM", "reported_user_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Target not found"}


def test_unknown_event_returns_404(client: TestClient, users: dict[str, UUID]) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={"report_type": "SPAM", "reported_event_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Target not found"}


def test_deleted_user_returns_404(client: TestClient, users: dict[str, UUID]) -> None:
    headers = login(client, USER_A_EMAIL)
    db_generator = db_session()
    db = next(db_generator)
    try:
        target = db.get(UserModel, users["b"])
        target.deleted_at = NOW
        db.commit()
    finally:
        db_generator.close()

    response = client.post(
        "/reports",
        headers=headers,
        json={"report_type": "SPAM", "reported_user_id": str(users["b"])},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Target not found"}


def test_invite_only_event_the_author_cannot_open_returns_404(
    client: TestClient, users: dict[str, UUID]
) -> None:
    event_id = create_event(users["b"], privacy=EventPrivacyEnum.INVITE_ONLY)

    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={"report_type": "SPAM", "reported_event_id": str(event_id)},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Target not found"}


def test_without_token_returns_401(client: TestClient, users: dict[str, UUID]) -> None:
    response = client.post(
        "/reports",
        json={"report_type": "SPAM", "reported_user_id": str(users["b"])},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_second_report_for_the_same_user_returns_409_while_pending(
    client: TestClient, users: dict[str, UUID]
) -> None:
    headers = login(client, USER_A_EMAIL)
    payload = {"report_type": "SPAM", "reported_user_id": str(users["b"])}
    assert client.post("/reports", headers=headers, json=payload).status_code == 201

    response = client.post(
        "/reports",
        headers=headers,
        json={**payload, "report_type": "HARASSMENT"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Report already under review"}
    assert query_scalar(select(func.count()).select_from(ReportModel)) == 1


def test_second_report_for_the_same_event_returns_409_while_pending(
    client: TestClient, users: dict[str, UUID]
) -> None:
    event_id = create_event(users["b"])
    headers = login(client, USER_A_EMAIL)
    payload = {"report_type": "SPAM", "reported_event_id": str(event_id)}
    assert client.post("/reports", headers=headers, json=payload).status_code == 201

    response = client.post("/reports", headers=headers, json=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "Report already under review"}


def test_report_is_allowed_again_once_the_previous_one_is_not_pending(
    client: TestClient, users: dict[str, UUID]
) -> None:
    headers = login(client, USER_A_EMAIL)
    payload = {"report_type": "SPAM", "reported_user_id": str(users["b"])}
    assert client.post("/reports", headers=headers, json=payload).status_code == 201

    db_generator = db_session()
    db = next(db_generator)
    try:
        report = db.scalar(select(ReportModel))
        report.status = ReportStatusEnum.REVIEWED
        db.commit()
    finally:
        db_generator.close()

    assert client.post("/reports", headers=headers, json=payload).status_code == 201


def test_other_authors_and_other_targets_do_not_conflict(
    client: TestClient, users: dict[str, UUID]
) -> None:
    headers_a = login(client, USER_A_EMAIL)
    headers_c = login(client, USER_C_EMAIL)
    event_id = create_event(users["b"])

    first = client.post(
        "/reports",
        headers=headers_a,
        json={"report_type": "SPAM", "reported_user_id": str(users["b"])},
    )
    other_author = client.post(
        "/reports",
        headers=headers_c,
        json={"report_type": "SPAM", "reported_user_id": str(users["b"])},
    )
    other_target = client.post(
        "/reports",
        headers=headers_a,
        json={"report_type": "SPAM", "reported_user_id": str(users["c"])},
    )
    event_target = client.post(
        "/reports",
        headers=headers_a,
        json={"report_type": "SPAM", "reported_event_id": str(event_id)},
    )

    assert [
        first.status_code,
        other_author.status_code,
        other_target.status_code,
        event_target.status_code,
    ] == [201, 201, 201, 201]


def test_description_is_optional_and_trimmed(
    client: TestClient, users: dict[str, UUID]
) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={
            "report_type": "OTHER",
            "reported_user_id": str(users["b"]),
            "description": "   motivo   ",
        },
    )

    assert response.status_code == 201
    assert query_scalar(select(ReportModel)).description == "motivo"


def test_description_over_the_limit_returns_422(
    client: TestClient, users: dict[str, UUID]
) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={
            "report_type": "OTHER",
            "reported_user_id": str(users["b"]),
            "description": "x" * 1001,
        },
    )

    assert response.status_code == 422
    assert query_scalar(select(func.count()).select_from(ReportModel)) == 0


def test_reporting_has_no_side_effects(
    client: TestClient, users: dict[str, UUID]
) -> None:
    event_id = create_event(users["b"])
    headers = login(client, USER_A_EMAIL)

    assert (
        client.post(
            "/reports",
            headers=headers,
            json={"report_type": "SPAM", "reported_user_id": str(users["b"])},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/reports",
            headers=headers,
            json={"report_type": "SPAM", "reported_event_id": str(event_id)},
        ).status_code
        == 201
    )

    for model in (UserConnectionModel, UserBlockModel, NotificationModel):
        assert query_scalar(select(func.count()).select_from(model)) == 0
    event = query_scalar(select(EventModel))
    assert event.event_privacy is EventPrivacyEnum.PUBLIC
    assert event.event_status is EventStatusEnum.PUBLISHED
    assert event.deleted_at is None
    assert (
        client.get("/users/me", headers=login(client, USER_B_EMAIL)).status_code == 200
    )
