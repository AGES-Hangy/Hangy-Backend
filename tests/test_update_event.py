from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.domain.enums import EventStatusEnum, UserRoleEnum, UserTypeEnum
from app.domain.services.event_location import approximate_point
from app.domain.services.image_upload import ImageStorageUnavailableError
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import EventModel, UserModel
from tests import test_create_event
from tests.test_create_event import RUNNING_ID, auth_header, payload


@pytest.fixture
def event_client() -> tuple[TestClient, sessionmaker[Session]]:
    yield from test_create_event.client.__wrapped__()


def create_event(test_client: TestClient) -> UUID:
    response = test_client.post("/events", json=payload(), headers=auth_header())
    assert response.status_code == 201
    return UUID(response.json()["event_id"])


def header_for(user_id: UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


def test_organizer_can_update_event_fields_and_tags(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    starts_at = datetime.now(UTC) + timedelta(days=3)

    response = test_client.patch(
        f"/events/{event_id}",
        json={
            "title": "Pelada no Parcao - novo horario",
            "description": "Agora no campo 2",
            "event_date": starts_at.isoformat(),
            "end_date": (starts_at + timedelta(hours=2)).isoformat(),
            "location": {"latitude": -30.03, "longitude": -51.22},
            "location_name": "Campo 2",
            "cover_photo_url": "https://images.hangy.test/events/covers/new-cover.png",
            "tag_ids": [str(RUNNING_ID)],
        },
        headers=auth_header(),
    )

    assert response.status_code == 200
    response_body = response.json()
    assert response_body["event_id"] == str(event_id)
    assert response_body["title"] == "Pelada no Parcao - novo horario"
    assert response_body["status"] == "PUBLISHED"
    assert response_body["updated_at"] is not None
    assert datetime.fromisoformat(response_body["event_date"]).replace(tzinfo=UTC) == (
        starts_at
    )

    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_description == "Agora no campo 2"
        assert event.location_name == "Campo 2"
        assert (
            event.cover_photo_url
            == "https://images.hangy.test/events/covers/new-cover.png"
        )
        assert event.event_latitude == -30.03
        assert event.event_longitude == -51.22
        assert [tag.tag_id for tag in event.tags] == [RUNNING_ID]


def test_organizer_can_clear_nullable_event_fields(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)

    response = test_client.patch(
        f"/events/{event_id}",
        json={
            "description": None,
            "location_name": None,
            "cover_photo_url": None,
            "tag_ids": [],
        },
        headers=auth_header(),
    )

    assert response.status_code == 200
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_description is None
        assert event.location_name is None
        assert event.cover_photo_url is None
        assert event.tags == []


def test_only_the_organizer_can_update_an_event(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    other_user_id = uuid4()
    with session_factory() as db:
        db.add(
            UserModel(
                user_id=other_user_id,
                user_type=UserTypeEnum.PERSONAL,
                role=UserRoleEnum.USER,
                email="other@hangy.test",
                password_hash="hash",
                name="Outra Pessoa",
            )
        )
        db.commit()

    response = test_client.patch(
        f"/events/{event_id}",
        json={"title": "Tentativa"},
        headers=header_for(other_user_id),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Only the organizer can edit this event"}


def test_an_event_cannot_be_moved_to_the_past(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = event_client
    event_id = create_event(test_client)

    response = test_client.patch(
        f"/events/{event_id}",
        json={"event_date": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
        headers=auth_header(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Event date must be in the future"}


def test_a_finished_event_cannot_be_updated(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        event.event_status = EventStatusEnum.FINISHED
        db.commit()

    response = test_client.patch(
        f"/events/{event_id}",
        json={"title": "Tentativa"},
        headers=auth_header(),
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Event already finished"}


def test_an_unknown_event_cannot_be_updated(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = event_client

    response = test_client.patch(
        f"/events/{uuid4()}",
        json={"title": "Tentativa"},
        headers=auth_header(),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Event not found"}


def test_openapi_documents_event_update(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, _ = event_client

    operation = test_client.get("/openapi.json").json()["paths"]["/events/{event_id}"][
        "patch"
    ]

    assert set(operation["responses"]) >= {"200", "400", "403", "404", "409", "422"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UpdateEventOutput"
    }


def test_editing_other_fields_keeps_the_approximate_point(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        original_point = (event.approx_latitude, event.approx_longitude)

    starts_at = datetime.now(UTC) + timedelta(days=5)
    response = test_client.patch(
        f"/events/{event_id}",
        json={
            "title": "Novo titulo",
            "event_date": starts_at.isoformat(),
            "end_date": (starts_at + timedelta(hours=2)).isoformat(),
            "location_name": "Campo 2",
            "location_neighborhood": "Moinhos de Vento",
            "location_city": "Porto Alegre",
        },
        headers=auth_header(),
    )

    assert response.status_code == 200
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.event_title == "Novo titulo"
        assert event.location_neighborhood == "Moinhos de Vento"
        assert event.location_city == "Porto Alegre"
        assert (event.approx_latitude, event.approx_longitude) == original_point


def test_editing_the_coordinates_recalculates_the_approximate_point(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        original_point = (event.approx_latitude, event.approx_longitude)

    response = test_client.patch(
        f"/events/{event_id}",
        json={"location": {"latitude": -29.9, "longitude": -51.1}},
        headers=auth_header(),
    )

    assert response.status_code == 200
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert (event.approx_latitude, event.approx_longitude) != original_point
        assert (event.approx_latitude, event.approx_longitude) == approximate_point(
            event_id, -29.9, -51.1
        )


def test_organizer_can_clear_the_neighborhood_and_city(
    event_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    test_client, session_factory = event_client
    response = test_client.post(
        "/events",
        json=payload(location_neighborhood="Partenon", location_city="Porto Alegre"),
        headers=auth_header(),
    )
    event_id = UUID(response.json()["event_id"])

    untouched = test_client.patch(
        f"/events/{event_id}", json={"title": "Outro"}, headers=auth_header()
    )
    assert untouched.status_code == 200
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.location_neighborhood == "Partenon"
        assert event.location_city == "Porto Alegre"

    cleared = test_client.patch(
        f"/events/{event_id}",
        json={"location_neighborhood": None, "location_city": None},
        headers=auth_header(),
    )
    assert cleared.status_code == 200
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event is not None
        assert event.location_neighborhood is None
        assert event.location_city is None


@pytest.mark.parametrize("resend_cover", [False, True])
def test_editing_with_unchanged_external_cover_keeps_legacy_url(
    event_client, image_storage, monkeypatch, resend_cover
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    legacy_url = "https://picsum.photos/400/300"
    with session_factory() as db:
        db.get(EventModel, event_id).cover_photo_url = legacy_url
        db.commit()
    owns = Mock(wraps=image_storage.owns)
    delete = Mock(wraps=image_storage.delete)
    monkeypatch.setattr(image_storage, "owns", owns)
    monkeypatch.setattr(image_storage, "delete", delete)
    body = {"title": "Titulo novo"}
    if resend_cover:
        body["cover_photo_url"] = legacy_url

    response = test_client.patch(
        f"/events/{event_id}", json=body, headers=auth_header()
    )

    assert response.status_code == 200
    owns.assert_not_called()
    delete.assert_not_called()
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event.cover_photo_url == legacy_url
        assert event.event_title == "Titulo novo"


@pytest.mark.parametrize("url", ["https://external.test/new.png", ""])
def test_replacing_cover_with_external_url_changes_nothing(
    event_client, image_storage, monkeypatch, url
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    delete = Mock(wraps=image_storage.delete)
    monkeypatch.setattr(image_storage, "delete", delete)

    response = test_client.patch(
        f"/events/{event_id}",
        json={"title": "Nao deve salvar", "cover_photo_url": url},
        headers=auth_header(),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid cover photo URL"}
    delete.assert_not_called()
    with session_factory() as db:
        event = db.get(EventModel, event_id)
        assert event.cover_photo_url == payload()["cover_photo_url"]
        assert event.event_title == payload()["title"]


@pytest.mark.parametrize("remove_cover", [False, True])
def test_previous_cover_is_deleted_only_after_commit(
    event_client, image_storage, monkeypatch, remove_cover
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    old_url = image_storage.upload("events/covers/cover.png", b"old", "image/png")
    new_url = (
        None
        if remove_cover
        else image_storage.upload("events/covers/new.png", b"new", "image/png")
    )
    operations = []
    commit = Session.commit
    delete = image_storage.delete

    def record_commit(session):
        commit(session)
        operations.append("commit")

    def delete_after_commit(url):
        assert operations == ["commit"]
        assert url == old_url
        with session_factory() as db:
            assert db.get(EventModel, event_id).cover_photo_url == new_url
        operations.append("delete")
        delete(url)

    monkeypatch.setattr(Session, "commit", record_commit)
    monkeypatch.setattr(image_storage, "delete", delete_after_commit)

    response = test_client.patch(
        f"/events/{event_id}", json={"cover_photo_url": new_url}, headers=auth_header()
    )

    assert response.status_code == 200
    assert operations == ["commit", "delete"]
    assert old_url not in image_storage.objects
    if new_url:
        assert new_url in image_storage.objects


@pytest.mark.parametrize("remove_cover", [False, True])
def test_external_old_cover_is_never_deleted(
    event_client, image_storage, monkeypatch, remove_cover
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    with session_factory() as db:
        db.get(EventModel, event_id).cover_photo_url = "https://picsum.photos/400/300"
        db.commit()
    delete = Mock(wraps=image_storage.delete)
    monkeypatch.setattr(image_storage, "delete", delete)
    new_url = None if remove_cover else payload()["cover_photo_url"]

    response = test_client.patch(
        f"/events/{event_id}", json={"cover_photo_url": new_url}, headers=auth_header()
    )

    assert response.status_code == 200
    delete.assert_not_called()
    with session_factory() as db:
        assert db.get(EventModel, event_id).cover_photo_url == new_url


def test_unchanged_bucket_cover_is_not_deleted(
    event_client, image_storage, monkeypatch
):
    test_client, _ = event_client
    event_id = create_event(test_client)
    delete = Mock(wraps=image_storage.delete)
    monkeypatch.setattr(image_storage, "delete", delete)

    response = test_client.patch(
        f"/events/{event_id}",
        json={"cover_photo_url": payload()["cover_photo_url"]},
        headers=auth_header(),
    )

    assert response.status_code == 200
    delete.assert_not_called()


def test_delete_failure_is_logged_and_does_not_undo_saved_cover(
    event_client, image_storage, monkeypatch, caplog
) -> None:
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    monkeypatch.setattr(
        image_storage, "delete", Mock(side_effect=ImageStorageUnavailableError)
    )

    response = test_client.patch(
        f"/events/{event_id}", json={"cover_photo_url": None}, headers=auth_header()
    )

    assert response.status_code == 200
    image_storage.delete.assert_called_once_with(payload()["cover_photo_url"])
    assert "Failed to delete previous cover" in caplog.text
    with session_factory() as db:
        assert db.get(EventModel, event_id).cover_photo_url is None


def test_failed_save_never_deletes_previous_cover(
    event_client, image_storage, monkeypatch
):
    test_client, session_factory = event_client
    event_id = create_event(test_client)
    old_url = image_storage.upload("events/covers/cover.png", b"old", "image/png")
    delete = Mock(wraps=image_storage.delete)
    monkeypatch.setattr(image_storage, "delete", delete)
    monkeypatch.setattr(
        SqlAlchemyEventRepository,
        "update",
        Mock(side_effect=RuntimeError("save failed")),
    )

    with pytest.raises(RuntimeError, match="save failed"):
        test_client.patch(
            f"/events/{event_id}", json={"cover_photo_url": None}, headers=auth_header()
        )

    delete.assert_not_called()
    assert old_url in image_storage.objects
    with session_factory() as db:
        assert db.get(EventModel, event_id).cover_photo_url == old_url
