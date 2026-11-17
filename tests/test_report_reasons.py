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
    ReportStatusEnum,
    ReportTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    ReportModel,
)
from app.main import app

USER_EMAIL = "ana@hangy.com"
USER_PASSWORD = "strong-password"
OTHER_EMAIL = "bruno@hangy.com"
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


def register(client: TestClient, email: str, cpf: str) -> tuple[UUID, dict[str, str]]:
    response = client.post(
        "/auth/register",
        json={
            "user_type": "PERSONAL",
            "email": email,
            "password": USER_PASSWORD,
            "name": "Ana Souza",
            "cpf": cpf,
            "phone": "51999990000",
            "date_of_birth": "2000-04-12",
            "state": "RS",
            "city": "Porto Alegre",
            "accepted_terms_version": "2026-08-01",
        },
    )
    assert response.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": USER_PASSWORD})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return UUID(response.json()["user"]["id"]), headers


@pytest.fixture
def me(client: TestClient) -> tuple[UUID, dict[str, str]]:
    return register(client, USER_EMAIL, "52998224725")


@pytest.fixture
def other(client: TestClient) -> tuple[UUID, dict[str, str]]:
    return register(client, OTHER_EMAIL, "11144477735")


def db():
    return next(app.dependency_overrides[get_db]())


def make_event(
    creator_id: UUID,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
    participant: tuple[UUID, EventParticipantStatusEnum] | None = None,
) -> UUID:
    session = db()
    event = EventModel(
        event_id=uuid4(),
        event_creator_id=creator_id,
        event_title="Churrasco",
        event_latitude=0.0,
        event_longitude=0.0,
        approx_latitude=0.0,
        approx_longitude=0.0,
        starts_at=NOW + timedelta(days=5),
        ends_at=NOW + timedelta(days=5, hours=2),
        event_status="PUBLISHED",
        event_privacy=privacy,
    )
    session.add(event)
    session.commit()
    if participant is not None:
        session.add(
            EventParticipantModel(
                event_id=event.event_id,
                user_id=participant[0],
                status=participant[1],
            )
        )
        session.commit()
    return event.event_id


def open_report(
    author_id: UUID,
    report_type: ReportTypeEnum,
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
    *,
    user_id: UUID | None = None,
    event_id: UUID | None = None,
) -> None:
    session = db()
    session.add(
        ReportModel(
            report_creator_id=author_id,
            reported_user_id=user_id,
            reported_event_id=event_id,
            report_type=report_type,
            description="",
            status=status,
        )
    )
    session.commit()


def get_reasons(client, headers, target, target_id):
    return client.get(
        "/reports/reasons",
        params={"target": target, "target_id": str(target_id)},
        headers=headers,
    )


def by_code(response) -> dict[str, dict]:
    return {reason["code"]: reason for reason in response.json()}


def test_user_target_returns_the_user_reasons(client, me, other) -> None:
    response = get_reasons(client, me[1], "USER", other[0])

    assert response.status_code == 200
    body = response.json()
    assert body[0] == {
        "code": "HARASSMENT",
        "label": "Assédio ou intimidação",
        "scope": "CONTENT",
        "available": True,
        "unavailable_reason": None,
    }
    assert {reason["code"] for reason in body} <= {t.value for t in ReportTypeEnum}
    assert "FAKE_PROFILE" in by_code(response)
    assert "MISLEADING_EVENT" not in by_code(response)
    assert {reason["scope"] for reason in body} == {"CONTENT"}
    assert all(reason["available"] for reason in body)


def test_event_target_returns_a_different_list_with_scopes(client, me, other) -> None:
    event_id = make_event(other[0])

    user_codes = list(by_code(get_reasons(client, me[1], "USER", other[0])))
    response = get_reasons(client, me[1], "EVENT", event_id)

    assert response.status_code == 200
    reasons = by_code(response)
    assert list(reasons) != user_codes
    assert "FAKE_PROFILE" not in reasons
    assert {code for code, r in reasons.items() if r["scope"] == "CONTENT"} == {
        "INAPPROPRIATE_CONTENT",
        "HATE_SPEECH",
        "SPAM",
        "OTHER",
    }
    assert {code for code, r in reasons.items() if r["scope"] == "EXPERIENCE"} == {
        "MISLEADING_EVENT",
        "HARASSMENT",
        "SAFETY_CONCERN",
    }
    assert reasons["MISLEADING_EVENT"]["label"] == "Evento enganoso"
    assert all(
        set(r) == {"code", "label", "scope", "available", "unavailable_reason"}
        for r in reasons.values()
    )


def test_public_event_non_participant_only_gets_content_reasons(
    client, me, other
) -> None:
    event_id = make_event(other[0])

    reasons = by_code(get_reasons(client, me[1], "EVENT", event_id))

    for code, reason in reasons.items():
        if reason["scope"] == "CONTENT":
            assert reason["available"] is True, code
            assert reason["unavailable_reason"] is None
        else:
            assert reason["available"] is False, code
            assert reason["unavailable_reason"] == "PARTICIPANTS_ONLY"


def test_participant_gets_every_reason_even_before_the_event_starts(
    client, me, other
) -> None:
    event_id = make_event(
        other[0], participant=(me[0], EventParticipantStatusEnum.CONFIRMED)
    )

    response = get_reasons(client, me[1], "EVENT", event_id)

    assert response.status_code == 200
    assert all(
        r["available"] and r["unavailable_reason"] is None for r in response.json()
    )


def test_open_reports_make_only_their_reason_already_reported(
    client, me, other
) -> None:
    event_id = make_event(
        other[0], participant=(me[0], EventParticipantStatusEnum.CONFIRMED)
    )
    open_report(me[0], ReportTypeEnum.HATE_SPEECH, event_id=event_id)
    open_report(
        me[0], ReportTypeEnum.HARASSMENT, ReportStatusEnum.REVIEWED, event_id=event_id
    )
    open_report(
        me[0], ReportTypeEnum.SPAM, ReportStatusEnum.RESOLVED, event_id=event_id
    )
    open_report(
        me[0], ReportTypeEnum.OTHER, ReportStatusEnum.REJECTED, event_id=event_id
    )

    reasons = by_code(get_reasons(client, me[1], "EVENT", event_id))

    unavailable = {c for c, r in reasons.items() if not r["available"]}
    assert unavailable == {"HATE_SPEECH", "HARASSMENT"}
    assert reasons["HATE_SPEECH"]["unavailable_reason"] == "ALREADY_REPORTED"
    assert reasons["HARASSMENT"]["unavailable_reason"] == "ALREADY_REPORTED"


def test_participants_only_wins_over_already_reported(client, me, other) -> None:
    event_id = make_event(other[0])
    open_report(me[0], ReportTypeEnum.HARASSMENT, event_id=event_id)
    open_report(me[0], ReportTypeEnum.SPAM, event_id=event_id)

    reasons = by_code(get_reasons(client, me[1], "EVENT", event_id))

    assert reasons["HARASSMENT"]["unavailable_reason"] == "PARTICIPANTS_ONLY"
    assert reasons["SPAM"]["unavailable_reason"] == "ALREADY_REPORTED"


def test_user_reasons_flag_open_reports_of_this_author_and_target_only(
    client, me, other
) -> None:
    third_id, _ = register(client, "carla@hangy.com", "39053344705")
    open_report(me[0], ReportTypeEnum.HARASSMENT, user_id=other[0])
    open_report(me[0], ReportTypeEnum.SPAM, user_id=third_id)
    open_report(other[0], ReportTypeEnum.FAKE_PROFILE, user_id=third_id)

    reasons = by_code(get_reasons(client, me[1], "USER", other[0]))

    assert {c for c, r in reasons.items() if not r["available"]} == {"HARASSMENT"}
    assert reasons["HARASSMENT"]["unavailable_reason"] == "ALREADY_REPORTED"


@pytest.mark.parametrize(
    "privacy", [EventPrivacyEnum.PRIVATE, EventPrivacyEnum.INVITE_ONLY]
)
@pytest.mark.parametrize("participation", [None, EventParticipantStatusEnum.PENDING])
def test_private_and_invite_event_without_approved_participation_returns_403(
    client, me, other, privacy, participation
) -> None:
    event_id = make_event(
        other[0],
        privacy,
        participant=(me[0], participation) if participation else None,
    )

    response = get_reasons(client, me[1], "EVENT", event_id)

    assert response.status_code == 403
    assert response.json() == {"detail": "Only participants can report this event"}
    assert str(event_id) not in response.text


@pytest.mark.parametrize(
    "privacy", [EventPrivacyEnum.PRIVATE, EventPrivacyEnum.INVITE_ONLY]
)
def test_private_and_invite_event_participant_gets_every_reason(
    client, me, other, privacy
) -> None:
    event_id = make_event(
        other[0], privacy, participant=(me[0], EventParticipantStatusEnum.CONFIRMED)
    )

    response = get_reasons(client, me[1], "EVENT", event_id)

    assert response.status_code == 200
    assert all(r["available"] for r in response.json())


def test_own_profile_and_own_event_return_403(client, me) -> None:
    event_id = make_event(me[0])

    for target, target_id in (("USER", me[0]), ("EVENT", event_id)):
        response = get_reasons(client, me[1], target, target_id)
        assert response.status_code == 403
        assert response.json() == {"detail": "Cannot report yourself"}


def test_unknown_targets_return_404(client, me) -> None:
    for target in ("USER", "EVENT"):
        response = get_reasons(client, me[1], target, uuid4())
        assert response.status_code == 404
        assert response.json() == {"detail": "Target not found"}


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"target": "USER"},
        {"target_id": str(uuid4())},
        {"target": "USER", "target_id": "not-a-uuid"},
        {"target": "BUSINESS", "target_id": str(uuid4())},
        {"target": "user", "target_id": str(uuid4())},
    ],
)
def test_missing_or_invalid_params_return_422(client, me, params) -> None:
    response = client.get("/reports/reasons", params=params, headers=me[1])

    assert response.status_code == 422


def test_requires_authentication(client: TestClient) -> None:
    params = {"target": "USER", "target_id": str(uuid4())}

    response = client.get("/reports/reasons", params=params)
    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}

    response = client.get(
        "/reports/reasons",
        params=params,
        headers={"Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401
