import importlib.util
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.config import settings
from app.domain.entities import Event
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    LocationPrecisionEnum,
)
from app.domain.services import event_location
from app.domain.services.event_location import approximate_point, resolve_location

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20261011_01_add_event_approximate_location.py"
)
REAL_LATITUDE = -30.0512
REAL_LONGITUDE = -51.1789
APPROX_LATITUDE = -30.0531
APPROX_LONGITUDE = -51.1762
# Rounding in the trigonometry may land a hair outside the exact bounds.
TOLERANCE_M = 0.01


def distance_m(
    latitude: float, longitude: float, other_latitude: float, other_longitude: float
) -> float:
    """Great-circle distance, on the same sphere `approximate_point` uses."""
    delta_latitude = math.radians(other_latitude - latitude)
    delta_longitude = math.radians(other_longitude - longitude)
    a = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(math.radians(latitude))
        * math.cos(math.radians(other_latitude))
        * math.sin(delta_longitude / 2) ** 2
    )
    return 2 * event_location.EARTH_RADIUS_M * math.asin(math.sqrt(a))


def make_event(
    privacy: EventPrivacyEnum = EventPrivacyEnum.PRIVATE,
    neighborhood: str | None = "Partenon",
    city: str | None = "Porto Alegre",
) -> Event:
    now = datetime.now(UTC)
    return Event(
        event_id=uuid4(),
        event_creator_id=uuid4(),
        event_title="Futebol no Planet",
        event_latitude=REAL_LATITUDE,
        event_longitude=REAL_LONGITUDE,
        approx_latitude=APPROX_LATITUDE,
        approx_longitude=APPROX_LONGITUDE,
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
        event_status=EventStatusEnum.PUBLISHED,
        event_privacy=privacy,
        created_at=now,
        updated_at=now,
        location_name="Planet Ball — Av. Ipiranga, 6681",
        location_neighborhood=neighborhood,
        location_city=city,
    )


def assert_exact(event: Event, **viewer: object) -> None:
    location = resolve_location(event, **viewer)
    assert location.precision is LocationPrecisionEnum.EXACT
    assert (location.latitude, location.longitude) == (REAL_LATITUDE, REAL_LONGITUDE)
    assert location.label == "Planet Ball — Av. Ipiranga, 6681"
    assert location.radius_m is None


def assert_approximate(event: Event, **viewer: object) -> None:
    location = resolve_location(event, **viewer)
    assert location.precision is LocationPrecisionEnum.APPROXIMATE
    assert (location.latitude, location.longitude) == (
        APPROX_LATITUDE,
        APPROX_LONGITUDE,
    )
    assert location.label == "Partenon, Porto Alegre"
    assert location.radius_m == 500


def test_approximate_point_is_deterministic() -> None:
    event_id = uuid4()

    assert approximate_point(
        event_id, REAL_LATITUDE, REAL_LONGITUDE
    ) == approximate_point(event_id, REAL_LATITUDE, REAL_LONGITUDE)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (REAL_LATITUDE, REAL_LONGITUDE),
        (0.0, 0.0),
        (64.1466, -21.9426),
        # Next to the antimeridian and to a pole, where a flat offset breaks.
        (-16.5, 179.9999),
        (89.9999, 10.0),
    ],
)
def test_approximate_point_stays_between_150_and_350_meters_away(
    latitude: float, longitude: float
) -> None:
    for index in range(200):
        approx_latitude, approx_longitude = approximate_point(
            UUID(int=index), latitude, longitude
        )

        assert -90 <= approx_latitude <= 90
        assert -180 <= approx_longitude <= 180
        assert (
            150 - TOLERANCE_M
            <= distance_m(latitude, longitude, approx_latitude, approx_longitude)
            <= 350 + TOLERANCE_M
        )


def test_events_at_the_same_address_get_different_approximate_points() -> None:
    points = {
        approximate_point(UUID(int=index), REAL_LATITUDE, REAL_LONGITUDE)
        for index in range(50)
    }

    assert len(points) == 50


def test_approximate_point_depends_on_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_id = uuid4()
    point = approximate_point(event_id, REAL_LATITUDE, REAL_LONGITUDE)

    monkeypatch.setattr(
        event_location,
        "settings",
        replace(settings, location_obfuscation_secret="another-secret"),
    )

    assert approximate_point(event_id, REAL_LATITUDE, REAL_LONGITUDE) != point


def test_anyone_gets_the_exact_location_of_a_public_event() -> None:
    assert_exact(
        make_event(EventPrivacyEnum.PUBLIC),
        is_organizer=False,
        participation_status=None,
    )


def test_whoever_reached_an_invite_only_event_gets_its_exact_location() -> None:
    assert_exact(
        make_event(EventPrivacyEnum.INVITE_ONLY),
        is_organizer=False,
        participation_status=None,
    )


def test_the_organizer_gets_the_exact_location_of_a_private_event() -> None:
    assert_exact(make_event(), is_organizer=True, participation_status=None)


def test_a_confirmed_participant_gets_the_exact_location_of_a_private_event() -> None:
    assert_exact(
        make_event(),
        is_organizer=False,
        participation_status=EventParticipantStatusEnum.CONFIRMED,
    )


@pytest.mark.parametrize(
    "participation_status",
    [
        None,
        EventParticipantStatusEnum.PENDING,
        EventParticipantStatusEnum.REJECTED,
        EventParticipantStatusEnum.CANCELLED,
        EventParticipantStatusEnum.REMOVED,
    ],
)
def test_a_viewer_not_approved_gets_the_approximate_location_of_a_private_event(
    participation_status: EventParticipantStatusEnum | None,
) -> None:
    assert_approximate(
        make_event(), is_organizer=False, participation_status=participation_status
    )


def test_a_viewer_without_a_session_gets_the_approximate_location() -> None:
    # A shared link is resolved as a viewer who is neither the organizer nor
    # a participant.
    assert_approximate(make_event(), is_organizer=False, participation_status=None)


@pytest.mark.parametrize(
    ("neighborhood", "city", "label"),
    [
        ("Partenon", "Porto Alegre", "Partenon, Porto Alegre"),
        (None, "Porto Alegre", "Porto Alegre"),
        ("Partenon", None, "Partenon"),
        # Never the organizer's own text, which may be the full address.
        (None, None, None),
    ],
)
def test_approximate_label_never_falls_back_to_the_location_name(
    neighborhood: str | None, city: str | None, label: str | None
) -> None:
    location = resolve_location(
        make_event(neighborhood=neighborhood, city=city),
        is_organizer=False,
        participation_status=None,
    )

    assert location.label == label


def test_approximate_radius_comes_from_the_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        event_location,
        "settings",
        replace(settings, private_event_area_radius_m=800),
    )

    location = resolve_location(
        make_event(), is_organizer=False, participation_status=None
    )

    assert location.radius_m == 800


def test_migration_backfills_existing_events_and_can_be_reverted() -> None:
    spec = importlib.util.spec_from_file_location("migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    event = sa.Table(
        "event",
        metadata,
        sa.Column("event_id", sa.Uuid, primary_key=True),
        sa.Column("event_latitude", sa.Double, nullable=False),
        sa.Column("event_longitude", sa.Double, nullable=False),
        sa.Column("location_name", sa.String(120)),
    )
    existing = {
        uuid4(): (REAL_LATITUDE, REAL_LONGITUDE, "Planet Ball"),
        uuid4(): (-30.0277, -51.2287, None),
    }

    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(
            event.insert(),
            [
                {
                    "event_id": event_id,
                    "event_latitude": latitude,
                    "event_longitude": longitude,
                    "location_name": name,
                }
                for event_id, (latitude, longitude, name) in existing.items()
            ],
        )

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        columns = {
            column["name"]: column
            for column in sa.inspect(connection).get_columns("event")
        }
        assert columns["approx_latitude"]["nullable"] is False
        assert columns["approx_longitude"]["nullable"] is False
        assert columns["location_neighborhood"]["nullable"] is True
        assert columns["location_city"]["nullable"] is True

        assert {
            index["name"]: index["column_names"]
            for index in sa.inspect(connection).get_indexes("event")
        } == {"idx_event_approx_coordinates": ["approx_latitude", "approx_longitude"]}

        rows = connection.execute(
            sa.text(
                "SELECT event_id, approx_latitude, approx_longitude, "
                "location_neighborhood, location_city FROM event"
            )
        ).all()
        assert len(rows) == len(existing)
        for event_id, approx_latitude, approx_longitude, neighborhood, city in rows:
            latitude, longitude, _ = existing[UUID(event_id)]
            assert (approx_latitude, approx_longitude) == approximate_point(
                UUID(event_id), latitude, longitude
            )
            assert neighborhood is None
            assert city is None

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        assert {
            column["name"] for column in sa.inspect(connection).get_columns("event")
        } == {"event_id", "event_latitude", "event_longitude", "location_name"}
        assert sa.inspect(connection).get_indexes("event") == []
        assert set(
            connection.execute(sa.select(event.c.event_id, event.c.location_name))
        ) == {(event_id, name) for event_id, (_, _, name) in existing.items()}
    engine.dispose()
