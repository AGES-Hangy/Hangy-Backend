from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.enums import EventPrivacyEnum, UserRoleEnum
from app.infrastructure.push.after_commit import AfterCommitPushSender
from app.infrastructure.repository.models import (
    EventExperienceModel,
    ExperienceImagesModel,
    UserBlockModel,
    UserModel,
)
from tests.review_helpers import (
    add_event,
    add_participant,
    add_user,
    ended_event,
    headers_for,
)


def test_banned_organizer_and_profile_leave_discovery(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        viewer = add_user(db)
        banned = add_user(db, name="Banido Silva")
        active = add_user(db, name="Banido Ativo")
        add_event(db, banned, title="Festa escondida")
        add_event(db, active, title="Festa visivel")
        db.get(UserModel, banned).banned_at = datetime.now(UTC)
        db.commit()

    events = client.get("/search/events?q=Festa", headers=headers_for(viewer))
    people = client.get("/search/users?q=Banido", headers=headers_for(viewer))
    profile = client.get(f"/users/{banned}", headers=headers_for(viewer))

    assert events.status_code == 200
    assert "Festa escondida" not in events.text
    assert "Festa visivel" in events.text
    assert people.status_code == 200
    assert str(banned) not in people.text
    assert str(active) in people.text
    assert profile.status_code == 404


def test_an_elapsed_suspension_shows_the_profile_again(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        viewer = add_user(db)
        user = add_user(db)
        db.get(UserModel, user).suspended_until = datetime.now(UTC) - timedelta(
            minutes=1
        )
        db.commit()

    assert client.get(f"/users/{user}", headers=headers_for(viewer)).status_code == 200


def test_admin_cannot_moderate_another_admin(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        admin = add_user(db, role=UserRoleEnum.ADMIN)
        other_admin = add_user(db, role=UserRoleEnum.ADMIN)

    response = client.patch(
        f"/admin/users/{other_admin}/moderation",
        json={"action": "BAN"},
        headers=headers_for(admin),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Admins cannot moderate other admins"}


def _add_photo(db, event_id, author_id, url) -> None:
    participant_id = add_participant(db, event_id, author_id)
    experience = EventExperienceModel(
        event_participant_id=participant_id, description="Foi otimo"
    )
    db.add(experience)
    db.flush()
    db.add(ExperienceImagesModel(experience_id=experience.experience_id, photo_url=url))
    db.commit()


def test_private_gallery_is_only_for_organizer_and_confirmed(review_client) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        organizer = add_user(db)
        member = add_user(db)
        outsider = add_user(db)
        event_id = ended_event(db, organizer, privacy=EventPrivacyEnum.PRIVATE)
        _add_photo(db, event_id, member, "https://images.hangy.test/p.jpg")

    path = f"/events/{event_id}/photos"
    assert client.get(path, headers=headers_for(outsider)).status_code == 404
    assert client.get(path, headers=headers_for(member)).status_code == 200
    assert client.get(path, headers=headers_for(organizer)).status_code == 200


def test_gallery_hides_photos_from_authors_blocked_with_the_viewer(
    review_client,
) -> None:
    client, session_factory = review_client
    with session_factory() as db:
        organizer = add_user(db)
        blocked_author = add_user(db)
        other_author = add_user(db)
        viewer = add_user(db)
        event_id = ended_event(db, organizer)
        _add_photo(db, event_id, blocked_author, "https://images.hangy.test/b.jpg")
        _add_photo(db, event_id, other_author, "https://images.hangy.test/o.jpg")
        db.add(UserBlockModel(blocker_id=viewer, blocked_id=blocked_author))
        db.commit()

    response = client.get(f"/events/{event_id}/photos", headers=headers_for(viewer))

    assert response.status_code == 200
    assert "b.jpg" not in response.text
    assert "o.jpg" in response.text


class _ImmediateExecutor:
    def submit(self, fn, *args):
        fn(*args)


def _session():
    return sessionmaker(bind=create_engine("sqlite://"))()


def test_push_is_sent_only_after_commit_and_dropped_on_rollback() -> None:
    sender = Mock()
    sender.send.return_value = ["dead-token"]
    cleanup = Mock()

    committed = _session()
    push = AfterCommitPushSender(
        committed, sender, executor=_ImmediateExecutor(), cleanup=cleanup
    )
    assert push.send(["t1", "dead-token"], "Titulo", "Corpo", {"k": "v"}) == []
    sender.send.assert_not_called()
    committed.commit()
    sender.send.assert_called_once_with(
        ["t1", "dead-token"], "Titulo", "Corpo", {"k": "v"}
    )
    cleanup.assert_called_once_with(["dead-token"])

    rolled_back = _session()
    other_sender = Mock()
    push = AfterCommitPushSender(
        rolled_back, other_sender, executor=_ImmediateExecutor(), cleanup=cleanup
    )
    rolled_back.begin()
    push.send(["t2"], "Titulo", "Corpo", {})
    rolled_back.rollback()
    rolled_back.commit()
    other_sender.send.assert_not_called()


def test_push_failure_never_reaches_the_caller() -> None:
    sender = Mock()
    sender.send.side_effect = RuntimeError("expo down")
    session = _session()
    AfterCommitPushSender(session, sender, executor=_ImmediateExecutor()).send(
        ["t"], "a", "b", {}
    )
    session.commit()
    sender.send.assert_called_once()
