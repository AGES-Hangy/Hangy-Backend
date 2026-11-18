from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    NotificationTypeEnum,
)
from app.infrastructure.repository.models import (
    EventInviteLinkModel,
    EventModel,
    NotificationModel,
)
from tests.review_helpers import (
    add_event,
    add_participant,
    add_user,
    ended_event,
    headers_for,
)

COVERS = "https://images.hangy.test/events/covers"


def _notifications(session_factory, type_: NotificationTypeEnum) -> int:
    with session_factory() as db:
        return db.scalar(
            select(func.count())
            .select_from(NotificationModel)
            .where(NotificationModel.type == type_)
        )


def test_event_over_by_time_rejects_joining_editing_cancelling_and_approvals(
    review_client,
) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        organizer = add_user(db)
        guest = add_user(db)
        pending = add_user(db)
        public_id = ended_event(db, organizer)
        private_id = ended_event(db, organizer, privacy=EventPrivacyEnum.PRIVATE)
        participant_id = add_participant(
            db, private_id, pending, EventParticipantStatusEnum.PENDING
        )

    join = client.post(f"/events/{public_id}/participation", headers=headers_for(guest))
    edit = client.patch(
        f"/events/{public_id}", json={"title": "Novo"}, headers=headers_for(organizer)
    )
    cancel = client.patch(
        f"/events/{public_id}/cancel",
        json={"reason": "Chuva"},
        headers=headers_for(organizer),
    )
    approve = client.patch(
        f"/events/{private_id}/participants/{participant_id}",
        json={"status": "CONFIRMED"},
        headers=headers_for(organizer),
    )

    for response in (join, edit, cancel, approve):
        assert response.status_code == 409
        assert response.json() == {"detail": "Event already finished"}


def test_cancelling_twice_does_not_notify_participants_again(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        organizer = add_user(db)
        guest = add_user(db)
        event_id = add_event(db, organizer)
        add_participant(db, event_id, guest)

    first = client.patch(
        f"/events/{event_id}/cancel",
        json={"reason": "Chuva"},
        headers=headers_for(organizer),
    )
    second = client.patch(
        f"/events/{event_id}/cancel",
        json={"reason": "Chuva"},
        headers=headers_for(organizer),
    )

    assert first.status_code == second.status_code == 200
    assert _notifications(session_factory, NotificationTypeEnum.EVENT_CANCELLED) == 1


def test_cancelled_event_cannot_be_edited(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        organizer = add_user(db)
        event_id = add_event(db, organizer, status=EventStatusEnum.CANCELLED)

    response = client.patch(
        f"/events/{event_id}", json={"title": "Novo"}, headers=headers_for(organizer)
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Event is cancelled"}


def test_cover_must_be_an_event_cover_uploaded_by_the_organizer(
    review_client,
) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        organizer = add_user(db)
        other = add_user(db)
        event_id = add_event(db, organizer)

    for url in (
        f"https://images.hangy.test/users/{other}/profile.png",
        f"{COVERS}/{other}/cover.png",
        f"{COVERS}/legacy.png",
    ):
        response = client.patch(
            f"/events/{event_id}",
            json={"cover_photo_url": url},
            headers=headers_for(organizer),
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid cover photo URL"}

    own = client.patch(
        f"/events/{event_id}",
        json={"cover_photo_url": f"{COVERS}/{organizer}/cover.png"},
        headers=headers_for(organizer),
    )
    assert own.status_code == 200


def test_replacing_a_cover_never_deletes_images_other_events_or_users_use(
    review_client, image_storage
) -> None:
    client, session_factory = review_client
    shared = image_storage.upload("events/covers/shared.png", b"x", "image/png")
    profile = image_storage.upload("users/someone/photo.png", b"x", "image/png")
    with session_factory() as db:
        organizer = add_user(db)
        sharing = add_event(db, organizer, cover_photo_url=shared)
        add_event(db, organizer, cover_photo_url=shared)
        with_profile = add_event(db, organizer, cover_photo_url=profile)

    for event_id in (sharing, with_profile):
        response = client.patch(
            f"/events/{event_id}",
            json={"cover_photo_url": None},
            headers=headers_for(organizer),
        )
        assert response.status_code == 200

    assert shared in image_storage.objects
    assert profile in image_storage.objects


def test_resending_the_same_date_and_location_does_not_notify(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        organizer = add_user(db)
        guest = add_user(db)
        event_id = add_event(db, organizer)
        add_participant(db, event_id, guest)
        event = db.get(EventModel, event_id)
        same = {
            "event_date": event.starts_at.replace(tzinfo=UTC).isoformat(),
            "end_date": event.ends_at.replace(tzinfo=UTC).isoformat(),
            "location": {
                "latitude": event.event_latitude,
                "longitude": event.event_longitude,
            },
        }

    unchanged = client.patch(
        f"/events/{event_id}", json=same, headers=headers_for(organizer)
    )
    assert unchanged.status_code == 200
    assert _notifications(session_factory, NotificationTypeEnum.EVENT_UPDATED) == 0

    moved = client.patch(
        f"/events/{event_id}",
        json={"location": {"latitude": -29.0, "longitude": -51.0}},
        headers=headers_for(organizer),
    )
    assert moved.status_code == 200
    assert _notifications(session_factory, NotificationTypeEnum.EVENT_UPDATED) == 1


def test_invite_rules_for_organizer_ended_events_and_new_start(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        organizer = add_user(db)
        guest = add_user(db)
        event_id = add_event(db, organizer, privacy=EventPrivacyEnum.INVITE_ONLY)
        old_id = add_event(db, organizer, privacy=EventPrivacyEnum.INVITE_ONLY)
        db.add(
            EventInviteLinkModel(
                event_id=old_id,
                token="ended-token",
                created_by=organizer,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        old = db.get(EventModel, old_id)
        old.starts_at = datetime.now(UTC) - timedelta(hours=3)
        old.ends_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()

    link = client.post(
        f"/events/{event_id}/invite-link", headers=headers_for(organizer)
    )
    assert link.status_code in (200, 201)
    token = link.json()["token"]

    own = client.post(f"/invites/{token}/accept", headers=headers_for(organizer))
    ended = client.post("/invites/ended-token/accept", headers=headers_for(guest))

    assert own.status_code == 409
    assert own.json() == {"detail": "Event creator cannot join their own event"}
    assert ended.status_code == 409
    assert ended.json() == {"detail": "Event already finished"}

    new_start = datetime.now(UTC) + timedelta(days=3)
    moved = client.patch(
        f"/events/{event_id}",
        json={
            "event_date": new_start.isoformat(),
            "end_date": (new_start + timedelta(hours=2)).isoformat(),
        },
        headers=headers_for(organizer),
    )
    assert moved.status_code == 200
    with session_factory() as db:
        link_row = db.scalar(
            select(EventInviteLinkModel).where(EventInviteLinkModel.token == token)
        )
        assert link_row.expires_at.replace(tzinfo=UTC) == new_start
