from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.domain.entities import NewReport
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    ReportStatusEnum,
    ReportTypeEnum,
)
from app.domain.services import ReportAlreadyUnderReviewError
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    NotificationModel,
    ReportModel,
    UserBlockModel,
    UserConnectionModel,
    UserModel,
)
from app.infrastructure.repository.report import SqlAlchemyReportRepository
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
    starts_in: timedelta = timedelta(days=2),
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
            starts_at=NOW + starts_in,
            ends_at=NOW + starts_in + timedelta(hours=2),
            event_status=event_status,
            event_privacy=privacy,
        )
        db.add(event)
        db.commit()
        return event.event_id
    finally:
        db_generator.close()


def join_event(
    event_id: UUID,
    user_id: UUID,
    participation: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> None:
    db_generator = db_session()
    db = next(db_generator)
    try:
        db.add(
            EventParticipantModel(
                event_id=event_id, user_id=user_id, status=participation
            )
        )
        db.commit()
    finally:
        db_generator.close()


def set_report_status(status: ReportStatusEnum) -> None:
    db_generator = db_session()
    db = next(db_generator)
    try:
        for report in db.scalars(select(ReportModel)):
            report.status = status
        db.commit()
    finally:
        db_generator.close()


def post_report(client: TestClient, email: str, **payload):
    return client.post("/reports", headers=login(client, email), json=payload)


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
        json={"report_type": "SPAM", "reported_event_id": str(event_id)},
    )

    assert response.status_code == 201
    assert response.json()["report_type"] == "SPAM"
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


def test_reason_outside_the_enum_returns_422(
    client: TestClient, users: dict[str, UUID]
) -> None:
    response = client.post(
        "/reports",
        headers=login(client, USER_A_EMAIL),
        json={"report_type": "NOT_A_REASON", "reported_user_id": str(users["b"])},
    )

    assert response.status_code == 422
    assert query_scalar(select(func.count()).select_from(ReportModel)) == 0


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


def test_cancelled_event_returns_404(
    client: TestClient, users: dict[str, UUID]
) -> None:
    event_id = create_event(users["b"], event_status=EventStatusEnum.CANCELLED)

    response = post_report(
        client, USER_A_EMAIL, report_type="SPAM", reported_event_id=str(event_id)
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


@pytest.mark.parametrize(
    "open_status", [ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED]
)
def test_same_user_and_reason_returns_409_while_the_report_is_open(
    client: TestClient, users: dict[str, UUID], open_status: ReportStatusEnum
) -> None:
    payload = {"report_type": "HARASSMENT", "reported_user_id": str(users["b"])}
    assert post_report(client, USER_A_EMAIL, **payload).status_code == 201
    set_report_status(open_status)

    response = post_report(client, USER_A_EMAIL, **payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "Report already under review"}
    assert query_scalar(select(func.count()).select_from(ReportModel)) == 1


@pytest.mark.parametrize(
    "closed_status", [ReportStatusEnum.RESOLVED, ReportStatusEnum.REJECTED]
)
def test_same_user_and_reason_is_allowed_again_once_the_report_is_closed(
    client: TestClient, users: dict[str, UUID], closed_status: ReportStatusEnum
) -> None:
    payload = {"report_type": "HARASSMENT", "reported_user_id": str(users["b"])}
    assert post_report(client, USER_A_EMAIL, **payload).status_code == 201
    set_report_status(closed_status)

    assert post_report(client, USER_A_EMAIL, **payload).status_code == 201
    assert query_scalar(select(func.count()).select_from(ReportModel)) == 2


@pytest.mark.parametrize(
    "open_status", [ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED]
)
def test_another_reason_for_the_same_target_is_allowed_while_one_is_open(
    client: TestClient, users: dict[str, UUID], open_status: ReportStatusEnum
) -> None:
    target = {"reported_user_id": str(users["b"])}
    assert (
        post_report(
            client, USER_A_EMAIL, report_type="HARASSMENT", **target
        ).status_code
        == 201
    )
    set_report_status(open_status)

    for reason in ("FAKE_PROFILE", "SPAM"):
        assert (
            post_report(client, USER_A_EMAIL, report_type=reason, **target).status_code
            == 201
        )


def test_open_limit_is_per_reason_for_events_too(
    client: TestClient, users: dict[str, UUID]
) -> None:
    event_id = create_event(users["b"])
    target = {"reported_event_id": str(event_id)}
    assert (
        post_report(client, USER_A_EMAIL, report_type="SPAM", **target).status_code
        == 201
    )
    set_report_status(ReportStatusEnum.REVIEWED)

    same = post_report(client, USER_A_EMAIL, report_type="SPAM", **target)
    other = post_report(client, USER_A_EMAIL, report_type="HATE_SPEECH", **target)

    assert same.status_code == 409
    assert same.json() == {"detail": "Report already under review"}
    assert other.status_code == 201


def test_the_open_reason_limit_is_also_enforced_by_the_database(
    client: TestClient, users: dict[str, UUID]
) -> None:
    payload = {"report_type": "SPAM", "reported_user_id": str(users["b"])}
    assert post_report(client, USER_A_EMAIL, **payload).status_code == 201

    db_generator = db_session()
    db = next(db_generator)
    try:
        # Bypasses the service pre-check, as a concurrent request would.
        with pytest.raises(ReportAlreadyUnderReviewError):
            SqlAlchemyReportRepository(db).create(
                NewReport(
                    report_creator_id=users["a"],
                    report_type=ReportTypeEnum.SPAM,
                    reported_user_id=users["b"],
                )
            )
    finally:
        db_generator.close()


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


def test_other_integrity_errors_are_not_reported_as_409(
    client: TestClient, users: dict[str, UUID]
) -> None:
    headers = login(client, USER_A_EMAIL)
    first = client.post(
        "/reports",
        headers=headers,
        json={"report_type": "SPAM", "reported_user_id": str(users["b"])},
    )
    assert first.status_code == 201

    db_generator = db_session()
    db = next(db_generator)
    try:
        # A PENDING report by the same author exists, but this insert breaks the
        # exclusive-target CHECK, not the open-report unique indexes: the real
        # error must surface instead of being answered as "already under review".
        with pytest.raises(IntegrityError):
            SqlAlchemyReportRepository(db).create(
                NewReport(
                    report_creator_id=users["a"],
                    report_type=ReportTypeEnum.SPAM,
                )
            )
    finally:
        db_generator.close()


def test_report_own_profile_returns_400(
    client: TestClient, users: dict[str, UUID]
) -> None:
    response = post_report(
        client, USER_A_EMAIL, report_type="SPAM", reported_user_id=str(users["a"])
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot report yourself"}
    assert query_scalar(select(func.count()).select_from(ReportModel)) == 0


@pytest.mark.parametrize("privacy", list(EventPrivacyEnum))
def test_report_own_event_returns_400(
    client: TestClient, users: dict[str, UUID], privacy: EventPrivacyEnum
) -> None:
    event_id = create_event(users["a"], privacy=privacy)

    response = post_report(
        client, USER_A_EMAIL, report_type="SPAM", reported_event_id=str(event_id)
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Cannot report yourself"}


def test_public_event_non_participant_can_report_content_but_not_experience(
    client: TestClient, users: dict[str, UUID]
) -> None:
    event_id = create_event(users["b"])
    target = {"reported_event_id": str(event_id)}

    for reason in ("INAPPROPRIATE_CONTENT", "HATE_SPEECH", "SPAM", "OTHER"):
        response = post_report(client, USER_A_EMAIL, report_type=reason, **target)
        assert response.status_code == 201, reason

    for reason in ("MISLEADING_EVENT", "HARASSMENT", "SAFETY_CONCERN"):
        response = post_report(client, USER_A_EMAIL, report_type=reason, **target)
        assert response.status_code == 403, reason
        assert response.json() == {"detail": "Reason requires participation"}


@pytest.mark.parametrize(
    "participation",
    [
        EventParticipantStatusEnum.PENDING,
        EventParticipantStatusEnum.REJECTED,
        EventParticipantStatusEnum.CANCELLED,
        EventParticipantStatusEnum.REMOVED,
    ],
)
def test_public_event_participation_that_is_not_approved_does_not_count(
    client: TestClient,
    users: dict[str, UUID],
    participation: EventParticipantStatusEnum,
) -> None:
    event_id = create_event(users["b"])
    join_event(event_id, users["a"], participation)

    response = post_report(
        client,
        USER_A_EMAIL,
        report_type="HARASSMENT",
        reported_event_id=str(event_id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Reason requires participation"}


def test_public_event_participant_can_report_experience_before_it_starts(
    client: TestClient, users: dict[str, UUID]
) -> None:
    event_id = create_event(users["b"], starts_in=timedelta(days=30))
    join_event(event_id, users["a"])

    for reason in ("MISLEADING_EVENT", "HARASSMENT", "SAFETY_CONCERN", "SPAM"):
        response = post_report(
            client, USER_A_EMAIL, report_type=reason, reported_event_id=str(event_id)
        )
        assert response.status_code == 201, reason


@pytest.mark.parametrize(
    "privacy", [EventPrivacyEnum.PRIVATE, EventPrivacyEnum.INVITE_ONLY]
)
@pytest.mark.parametrize("report_type", ["SPAM", "HARASSMENT"])
def test_private_and_invite_event_non_participant_returns_403(
    client: TestClient,
    users: dict[str, UUID],
    privacy: EventPrivacyEnum,
    report_type: str,
) -> None:
    event_id = create_event(users["b"], privacy=privacy)

    response = post_report(
        client, USER_A_EMAIL, report_type=report_type, reported_event_id=str(event_id)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only participants can report this event"}
    assert str(event_id) not in response.text
    assert query_scalar(select(func.count()).select_from(ReportModel)) == 0


@pytest.mark.parametrize(
    "privacy", [EventPrivacyEnum.PRIVATE, EventPrivacyEnum.INVITE_ONLY]
)
def test_private_and_invite_event_pending_request_returns_403(
    client: TestClient, users: dict[str, UUID], privacy: EventPrivacyEnum
) -> None:
    event_id = create_event(users["b"], privacy=privacy)
    join_event(event_id, users["a"], EventParticipantStatusEnum.PENDING)

    response = post_report(
        client, USER_A_EMAIL, report_type="SPAM", reported_event_id=str(event_id)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only participants can report this event"}


@pytest.mark.parametrize(
    "privacy", [EventPrivacyEnum.PRIVATE, EventPrivacyEnum.INVITE_ONLY]
)
@pytest.mark.parametrize("report_type", ["SPAM", "HARASSMENT", "MISLEADING_EVENT"])
def test_private_and_invite_event_approved_participant_can_report(
    client: TestClient,
    users: dict[str, UUID],
    privacy: EventPrivacyEnum,
    report_type: str,
) -> None:
    event_id = create_event(users["b"], privacy=privacy, starts_in=timedelta(days=9))
    join_event(event_id, users["a"])

    response = post_report(
        client, USER_A_EMAIL, report_type=report_type, reported_event_id=str(event_id)
    )

    assert response.status_code == 201
    assert str(users["a"]) not in response.text
