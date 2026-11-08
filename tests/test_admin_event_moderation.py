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
    AuditActionEnum,
    AuditTargetTypeEnum,
    EventModerationStatusEnum,
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
    ReportTypeEnum,
    UserRoleEnum,
    UserTypeEnum,
)
from app.infrastructure.repository import Base, get_db
from app.infrastructure.repository.models import (
    AuditLogModel,
    EventCancelledNotificationModel,
    EventModel,
    EventParticipantModel,
    NotificationModel,
    TagModel,
    UserModel,
    event_tag,
    user_tag,
)
from app.infrastructure.repository.models.report_model import ReportModel
from app.infrastructure.repository.notification import (
    SqlAlchemyNotificationRepository,
)
from app.main import app

ModerationClient = tuple[TestClient, sessionmaker[Session]]

FUTURE = datetime.now(UTC) + timedelta(days=3)
EVENT_TITLE = "Pelada no Parcão"


@pytest.fixture
def moderation_client() -> Iterator[ModerationClient]:
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
    *,
    role: UserRoleEnum = UserRoleEnum.USER,
    name: str = "Pessoa",
) -> UUID:
    user_id = uuid4()
    db.add(
        UserModel(
            user_id=user_id,
            user_type=UserTypeEnum.PERSONAL,
            role=role,
            email=f"{user_id}@hangy.test",
            password_hash="hash",
            name=name,
        )
    )
    db.commit()
    return user_id


def add_event(
    db: Session,
    creator_id: UUID,
    title: str = EVENT_TITLE,
    *,
    privacy: EventPrivacyEnum = EventPrivacyEnum.PUBLIC,
) -> UUID:
    event_id = uuid4()
    db.add(
        EventModel(
            event_id=event_id,
            event_creator_id=creator_id,
            event_title=title,
            event_latitude=0.0,
            event_longitude=0.0,
            starts_at=FUTURE,
            ends_at=FUTURE + timedelta(hours=3),
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=privacy,
        )
    )
    db.commit()
    return event_id


def add_participant(
    db: Session,
    event_id: UUID,
    user_id: UUID,
    status: EventParticipantStatusEnum = EventParticipantStatusEnum.CONFIRMED,
) -> None:
    db.add(EventParticipantModel(event_id=event_id, user_id=user_id, status=status))
    db.commit()


def add_event_report(
    db: Session,
    creator_id: UUID,
    event_id: UUID,
    *,
    status: ReportStatusEnum = ReportStatusEnum.PENDING,
) -> UUID:
    report_id = uuid4()
    db.add(
        ReportModel(
            report_id=report_id,
            report_creator_id=creator_id,
            reported_event_id=event_id,
            report_type=ReportTypeEnum.MISLEADING_EVENT,
            description="Evento enganoso",
            status=status,
            updated_at=datetime.now(UTC),
        )
    )
    db.commit()
    return report_id


def add_user_report(db: Session, creator_id: UUID, reported_user_id: UUID) -> UUID:
    report_id = uuid4()
    db.add(
        ReportModel(
            report_id=report_id,
            report_creator_id=creator_id,
            reported_user_id=reported_user_id,
            report_type=ReportTypeEnum.HARASSMENT,
            description="Mensagens ofensivas",
            status=ReportStatusEnum.PENDING,
            updated_at=datetime.now(UTC),
        )
    )
    db.commit()
    return report_id


def admin_headers(session_factory: sessionmaker[Session]) -> dict[str, str]:
    with session_factory() as db:
        return header_for(add_user(db, role=UserRoleEnum.ADMIN, name="Admin"))


def remove(
    client: TestClient,
    event_id: UUID,
    headers: dict[str, str],
    **body: object,
):
    return client.patch(
        f"/admin/events/{event_id}/moderation",
        json={"action": "REMOVE", **body},
        headers=headers,
    )


def event_row(session_factory: sessionmaker[Session], event_id: UUID) -> EventModel:
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        db.expunge(event)
        return event


def report_row(session_factory: sessionmaker[Session], report_id: UUID) -> ReportModel:
    with session_factory() as db:
        report = db.get(ReportModel, report_id)
        assert report is not None
        db.expunge(report)
        return report


def audit_rows(session_factory: sessionmaker[Session]) -> list[AuditLogModel]:
    with session_factory() as db:
        return list(db.scalars(select(AuditLogModel)).all())


def participation_status(
    session_factory: sessionmaker[Session], event_id: UUID, user_id: UUID
) -> EventParticipantStatusEnum:
    with session_factory() as db:
        return db.scalars(
            select(EventParticipantModel.status).where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.user_id == user_id,
            )
        ).one()


def notifications_of(
    session_factory: sessionmaker[Session], user_id: UUID
) -> list[tuple[NotificationTypeEnum, UUID]]:
    with session_factory() as db:
        rows = db.execute(
            select(NotificationModel.type, EventCancelledNotificationModel.event_id)
            .join(
                EventCancelledNotificationModel,
                EventCancelledNotificationModel.notification_id
                == NotificationModel.notification_id,
            )
            .where(NotificationModel.user_id == user_id)
        ).all()
        return [(row[0], row[1]) for row in rows]


def test_remove_with_report_soft_deletes_event_and_resolves_the_report(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        organizer_id = add_user(db, name="Rafael Costa")
        reporter_id = add_user(db)
        event_id = add_event(db, organizer_id)
        report_id = add_event_report(db, reporter_id, event_id)

    before = datetime.now(UTC)
    response = remove(client, event_id, header_for(admin_id), report_id=str(report_id))

    assert response.status_code == 200
    body = response.json()
    removed_at = datetime.fromisoformat(body["removed_at"])
    assert before <= removed_at <= datetime.now(UTC) + timedelta(seconds=1)
    assert body == {
        "event_id": str(event_id),
        "moderation_status": "REMOVED",
        "removed_at": body["removed_at"],
        "report_id": str(report_id),
        "report_status": "RESOLVED",
    }

    event = event_row(session_factory, event_id)
    assert event.moderation_status is EventModerationStatusEnum.REMOVED
    assert event.removed_at is not None
    assert event.deleted_at is not None
    report = report_row(session_factory, report_id)
    assert report.status is ReportStatusEnum.RESOLVED
    assert report.resolution_action is ReportResolutionActionEnum.EVENT_REMOVED
    assert report.resolved_by_id == admin_id
    assert report.resolved_at is not None


def test_remove_without_report_id_returns_null_report_fields(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        event_id = add_event(db, add_user(db))

    response = remove(client, event_id, header_for(admin_id))

    assert response.status_code == 200
    body = response.json()
    assert body["event_id"] == str(event_id)
    assert body["moderation_status"] == "REMOVED"
    assert body["removed_at"]
    assert body["report_id"] is None
    assert body["report_status"] is None
    assert (
        event_row(session_factory, event_id).moderation_status
        is EventModerationStatusEnum.REMOVED
    )


def test_other_open_reports_of_the_event_are_resolved_together(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        previous_admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Outra")
        organizer_id = add_user(db)
        reporter_id = add_user(db)
        event_id = add_event(db, organizer_id)
        other_event_id = add_event(db, organizer_id, "Outro evento")
        informed = add_event_report(db, reporter_id, event_id)
        pending = add_event_report(db, reporter_id, event_id)
        reviewed = add_event_report(
            db, reporter_id, event_id, status=ReportStatusEnum.REVIEWED
        )
        archived = add_event_report(
            db, reporter_id, event_id, status=ReportStatusEnum.REJECTED
        )
        resolved = add_event_report(
            db, reporter_id, event_id, status=ReportStatusEnum.RESOLVED
        )
        elsewhere = add_event_report(db, reporter_id, other_event_id)
        about_user = add_user_report(db, reporter_id, organizer_id)
        db.execute(
            ReportModel.__table__.update()
            .where(ReportModel.report_id == resolved)
            .values(
                resolved_by_id=previous_admin_id,
                resolution_action=ReportResolutionActionEnum.ARCHIVED,
            )
        )
        db.commit()

    response = remove(client, event_id, header_for(admin_id), report_id=str(informed))

    assert response.status_code == 200
    for report_id in (informed, pending, reviewed):
        report = report_row(session_factory, report_id)
        assert report.status is ReportStatusEnum.RESOLVED
        assert report.resolution_action is ReportResolutionActionEnum.EVENT_REMOVED
        assert report.resolved_by_id == admin_id
        assert report.resolved_at is not None
    # Closed reports, other events and profile reports are left alone.
    assert report_row(session_factory, archived).status is ReportStatusEnum.REJECTED
    untouched = report_row(session_factory, resolved)
    assert untouched.resolved_by_id == previous_admin_id
    assert untouched.resolution_action is ReportResolutionActionEnum.ARCHIVED
    assert report_row(session_factory, elsewhere).status is ReportStatusEnum.PENDING
    assert report_row(session_factory, about_user).status is ReportStatusEnum.PENDING


def test_open_reports_are_resolved_even_without_report_id(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        reporter_id = add_user(db)
        event_id = add_event(db, add_user(db))
        report_id = add_event_report(db, reporter_id, event_id)

    assert remove(client, event_id, header_for(admin_id)).status_code == 200

    report = report_row(session_factory, report_id)
    assert report.status is ReportStatusEnum.RESOLVED
    assert report.resolution_action is ReportResolutionActionEnum.EVENT_REMOVED
    assert report.resolved_by_id == admin_id


def test_removed_event_disappears_for_regular_users(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        organizer_id = add_user(db, name="Rafael")
        viewer_id = add_user(db, name="Viewer")
        macro = TagModel(tag_name="Esportes")
        db.add(macro)
        db.commit()
        db.execute(user_tag.insert().values(user_id=viewer_id, tag_id=macro.tag_id))
        event_id = add_event(db, organizer_id)
        kept_id = add_event(db, organizer_id, "Pelada que fica")
        for tagged_id in (event_id, kept_id):
            db.execute(
                event_tag.insert().values(event_id=tagged_id, tag_id=macro.tag_id)
            )
        db.commit()
    viewer = header_for(viewer_id)
    organizer = header_for(organizer_id)

    def snapshot() -> dict[str, list[str]]:
        feed = client.get("/feed", headers=viewer)
        search = client.get("/search", params={"q": "Pelada"}, headers=viewer)
        nearby = client.get(
            "/events/nearby",
            params={"latitude": 0, "longitude": 0, "radius_m": 3_000},
            headers=viewer,
        )
        created = client.get(f"/users/{organizer_id}/events", headers=organizer)
        for response in (feed, search, nearby, created):
            assert response.status_code == 200, response.text
        return {
            "feed": [
                item["title"]
                for section in feed.json()["sections"]
                for item in section["items"]
            ],
            "search": [item["title"] for item in search.json()["events"]["items"]],
            "map": [item["event_id"] for item in nearby.json()["items"]],
            "profile": [item["title"] for item in created.json()["created"]["items"]],
        }

    visible = snapshot()
    assert EVENT_TITLE in visible["feed"]
    assert EVENT_TITLE in visible["search"]
    assert str(event_id) in visible["map"]
    assert EVENT_TITLE in visible["profile"]
    assert client.get(f"/events/{event_id}", headers=viewer).status_code == 200

    assert remove(client, event_id, header_for(admin_id)).status_code == 200

    after = snapshot()
    assert after["feed"] == ["Pelada que fica"]
    assert after["search"] == ["Pelada que fica"]
    assert after["map"] == [str(kept_id)]
    assert after["profile"] == ["Pelada que fica"]
    for headers in (viewer, organizer):
        assert client.get(f"/events/{event_id}", headers=headers).status_code == 404
    assert client.get(f"/events/{kept_id}", headers=viewer).status_code == 200


def test_active_participations_are_cancelled_and_everyone_is_notified(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        organizer_id = add_user(db, name="Rafael")
        confirmed_id = add_user(db, name="Confirmado")
        pending_id = add_user(db, name="Pendente")
        rejected_id = add_user(db, name="Recusado")
        cancelled_id = add_user(db, name="Cancelou")
        removed_id = add_user(db, name="Removido")
        bystander_id = add_user(db, name="De fora")
        event_id = add_event(db, organizer_id, privacy=EventPrivacyEnum.PRIVATE)
        other_event_id = add_event(db, organizer_id, "Outro")
        add_participant(db, event_id, confirmed_id)
        add_participant(db, event_id, pending_id, EventParticipantStatusEnum.PENDING)
        add_participant(db, event_id, rejected_id, EventParticipantStatusEnum.REJECTED)
        add_participant(
            db, event_id, cancelled_id, EventParticipantStatusEnum.CANCELLED
        )
        add_participant(db, event_id, removed_id, EventParticipantStatusEnum.REMOVED)
        add_participant(db, other_event_id, bystander_id)

    assert remove(client, event_id, header_for(admin_id)).status_code == 200

    CANCELLED = EventParticipantStatusEnum.CANCELLED
    assert participation_status(session_factory, event_id, confirmed_id) is CANCELLED
    assert participation_status(session_factory, event_id, pending_id) is CANCELLED
    assert (
        participation_status(session_factory, event_id, rejected_id)
        is EventParticipantStatusEnum.REJECTED
    )
    assert (
        participation_status(session_factory, event_id, removed_id)
        is EventParticipantStatusEnum.REMOVED
    )
    assert (
        participation_status(session_factory, other_event_id, bystander_id)
        is EventParticipantStatusEnum.CONFIRMED
    )

    removed_notice = [(NotificationTypeEnum.EVENT_REMOVED, event_id)]
    for notified in (organizer_id, confirmed_id, pending_id):
        assert notifications_of(session_factory, notified) == removed_notice
    for ignored in (rejected_id, cancelled_id, removed_id, bystander_id, admin_id):
        assert notifications_of(session_factory, ignored) == []

    inbox = client.get("/notifications", headers=header_for(confirmed_id))
    assert inbox.status_code == 200
    items = inbox.json()["items"]
    assert [item["type"] for item in items] == ["EVENT_REMOVED"]
    assert items[0]["payload"] == {
        "event_id": str(event_id),
        "event_title": EVENT_TITLE,
    }


def test_organizer_who_also_participates_is_notified_once(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        organizer_id = add_user(db)
        event_id = add_event(db, organizer_id)
        add_participant(db, event_id, organizer_id)

    assert remove(client, event_id, header_for(admin_id)).status_code == 200

    assert notifications_of(session_factory, organizer_id) == [
        (NotificationTypeEnum.EVENT_REMOVED, event_id)
    ]


def test_notification_failure_does_not_block_the_removal(
    moderation_client: ModerationClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        event_id = add_event(db, add_user(db))

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("notification store is down")

    monkeypatch.setattr(SqlAlchemyNotificationRepository, "notify_event_removed", fail)

    response = remove(client, event_id, header_for(admin_id))

    assert response.status_code == 200
    assert (
        event_row(session_factory, event_id).moderation_status
        is EventModerationStatusEnum.REMOVED
    )
    assert len(audit_rows(session_factory)) == 1


def test_removal_does_not_touch_the_organizer_account(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        organizer_id = add_user(db, name="Rafael")
        event_id = add_event(db, organizer_id)

    assert remove(client, event_id, header_for(admin_id)).status_code == 200

    with session_factory() as db:
        organizer = db.get(UserModel, organizer_id)
        assert organizer is not None
        assert organizer.banned_at is None
        assert organizer.suspended_until is None
        assert organizer.deleted_at is None
    assert client.get("/users/me", headers=header_for(organizer_id)).status_code == 200


def test_removal_is_recorded_in_the_audit_log(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Maria Admin")
        organizer_id = add_user(db)
        event_id = add_event(db, organizer_id)
        other_event_id = add_event(db, organizer_id, "Outro evento")
    admin = header_for(admin_id)

    assert remove(client, event_id, admin).status_code == 200

    (row,) = audit_rows(session_factory)
    assert row.action is AuditActionEnum.EVENT_REMOVED
    assert row.target_type is AuditTargetTypeEnum.EVENT
    assert row.target_id == event_id
    assert row.target_label == EVENT_TITLE
    assert row.actor_id == admin_id
    assert row.created_at is not None

    listing = client.get(
        "/admin/audit-log", params={"target_type": "EVENT"}, headers=admin
    )
    assert listing.status_code == 200
    (item,) = listing.json()["items"]
    assert item["action"] == "EVENT_REMOVED"
    assert item["target_type"] == "EVENT"
    assert item["target_id"] == str(event_id)
    assert item["actor"] == {"id": str(admin_id), "name": "Você"}
    assert item["summary"] == f"Você removeu o evento {EVENT_TITLE}"
    other = client.get(
        "/admin/audit-log", params={"target_type": "USER"}, headers=admin
    )
    assert other.json()["items"] == []
    assert str(other_event_id) not in listing.text


def test_non_admin_receives_403_and_nothing_changes(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        user_id = add_user(db)
        event_id = add_event(db, user_id)

    response = remove(client, event_id, header_for(user_id))

    assert response.status_code == 403
    assert response.json() == {"detail": "Admin access required"}
    assert (
        event_row(session_factory, event_id).moderation_status
        is EventModerationStatusEnum.ACTIVE
    )
    assert audit_rows(session_factory) == []


def test_missing_or_invalid_token_receives_401(
    moderation_client: ModerationClient,
) -> None:
    client, _ = moderation_client
    url = f"/admin/events/{uuid4()}/moderation"
    body = {"action": "REMOVE"}

    assert client.patch(url, json=body).status_code == 401
    assert (
        client.patch(
            url, json=body, headers={"Authorization": "Bearer not-a-token"}
        ).status_code
        == 401
    )


def test_unknown_event_returns_404(moderation_client: ModerationClient) -> None:
    client, session_factory = moderation_client

    response = remove(client, uuid4(), admin_headers(session_factory))

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_event_deleted_for_another_reason_returns_404(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        event_id = add_event(db, add_user(db))
        db.execute(
            EventModel.__table__.update()
            .where(EventModel.event_id == event_id)
            .values(deleted_at=datetime.now(UTC))
        )
        db.commit()

    response = remove(client, event_id, header_for(admin_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_removing_twice_returns_409_and_keeps_the_first_removal(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        event_id = add_event(db, add_user(db))
    admin = header_for(admin_id)
    first = remove(client, event_id, admin)
    assert first.status_code == 200
    removed_at = event_row(session_factory, event_id).removed_at

    second = remove(client, event_id, admin)

    assert second.status_code == 409
    assert second.json() == {"detail": "Event already removed"}
    assert event_row(session_factory, event_id).removed_at == removed_at
    assert len(audit_rows(session_factory)) == 1


def test_resolved_report_returns_409_and_leaves_the_event_untouched(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        reporter_id = add_user(db)
        event_id = add_event(db, add_user(db))
        participant_id = add_user(db)
        add_participant(db, event_id, participant_id)
        resolved = add_event_report(
            db, reporter_id, event_id, status=ReportStatusEnum.RESOLVED
        )
        archived = add_event_report(
            db, reporter_id, event_id, status=ReportStatusEnum.REJECTED
        )
        open_report = add_event_report(db, reporter_id, event_id)

    for closed in (resolved, archived):
        response = remove(client, event_id, header_for(admin_id), report_id=str(closed))
        assert response.status_code == 409
        assert response.json() == {"detail": "Report already resolved"}

    assert (
        event_row(session_factory, event_id).moderation_status
        is EventModerationStatusEnum.ACTIVE
    )
    assert report_row(session_factory, open_report).status is ReportStatusEnum.PENDING
    assert (
        participation_status(session_factory, event_id, participant_id)
        is EventParticipantStatusEnum.CONFIRMED
    )
    assert audit_rows(session_factory) == []


def test_report_of_another_target_returns_400(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        reporter_id = add_user(db)
        organizer_id = add_user(db)
        event_id = add_event(db, organizer_id)
        other_event_id = add_event(db, organizer_id, "Outro evento")
        other_event_report = add_event_report(db, reporter_id, other_event_id)
        user_report = add_user_report(db, reporter_id, organizer_id)

    for wrong in (other_event_report, user_report):
        response = remove(client, event_id, header_for(admin_id), report_id=str(wrong))
        assert response.status_code == 400
        assert response.json() == {"detail": "Report does not belong to this event"}

    assert (
        event_row(session_factory, event_id).moderation_status
        is EventModerationStatusEnum.ACTIVE
    )
    assert (
        report_row(session_factory, other_event_report).status
        is ReportStatusEnum.PENDING
    )
    assert audit_rows(session_factory) == []


def test_unknown_report_returns_404(moderation_client: ModerationClient) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        event_id = add_event(db, add_user(db))

    response = remove(client, event_id, header_for(admin_id), report_id=str(uuid4()))

    assert response.status_code == 404
    assert response.json() == {"detail": "Report not found"}
    assert (
        event_row(session_factory, event_id).moderation_status
        is EventModerationStatusEnum.ACTIVE
    )


@pytest.mark.parametrize(
    "body",
    [
        {"action": "BAN"},
        {},
        {"action": "REMOVE", "unexpected": True},
        {"action": "REMOVE", "report_id": "not-a-uuid"},
    ],
)
def test_invalid_body_returns_422(
    moderation_client: ModerationClient, body: dict[str, object]
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Admin")
        event_id = add_event(db, add_user(db))

    response = client.patch(
        f"/admin/events/{event_id}/moderation",
        json=body,
        headers=header_for(admin_id),
    )

    assert response.status_code == 422
    assert (
        event_row(session_factory, event_id).moderation_status
        is EventModerationStatusEnum.ACTIVE
    )


def test_report_detail_shows_event_resolution_after_removal(
    moderation_client: ModerationClient,
) -> None:
    client, session_factory = moderation_client
    with session_factory() as db:
        admin_id = add_user(db, role=UserRoleEnum.ADMIN, name="Maria Admin")
        organizer_id = add_user(db, name="Rafael Costa")
        event_id = add_event(db, organizer_id)
        report_id = add_event_report(db, add_user(db), event_id)
    admin = header_for(admin_id)
    assert remove(client, event_id, admin, report_id=str(report_id)).status_code == 200

    response = client.get(f"/admin/reports/{report_id}", headers=admin)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "RESOLVED"
    assert body["resolution"]["action"] == "EVENT_REMOVED"
    assert body["resolution"]["resolved_by"] == {
        "id": str(admin_id),
        "name": "Maria Admin",
    }
    assert body["target"]["type"] == "EVENT"
    assert body["organizer"]["user_id"] == str(organizer_id)
    # The removed event no longer counts as one of the organizer's events.
    assert body["organizer"]["events_count"] == 0
