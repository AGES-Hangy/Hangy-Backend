"""add_event_approximate_location

Revision ID: 20261011_01
Revises: 20261008_01
Create Date: 2026-10-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.domain.services.event_location import approximate_point

revision: str = "20261011_01"
down_revision: str | Sequence[str] | None = "20261008_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

event = sa.table(
    "event",
    sa.column("event_id", sa.Uuid),
    sa.column("event_latitude", sa.Double),
    sa.column("event_longitude", sa.Double),
    sa.column("approx_latitude", sa.Double),
    sa.column("approx_longitude", sa.Double),
)


def upgrade() -> None:
    # Existing events keep both labels empty: nobody typed them, and guessing
    # from `location_name` could leak the address it may contain.
    op.add_column(
        "event", sa.Column("location_neighborhood", sa.String(120), nullable=True)
    )
    op.add_column("event", sa.Column("location_city", sa.String(120), nullable=True))
    op.add_column("event", sa.Column("approx_latitude", sa.Double(), nullable=True))
    op.add_column("event", sa.Column("approx_longitude", sa.Double(), nullable=True))

    # The point depends on LOCATION_OBFUSCATION_SECRET, so it cannot be written
    # as SQL: it is the same function the API uses for new events.
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(event.c.event_id, event.c.event_latitude, event.c.event_longitude)
    ).all()
    for event_id, latitude, longitude in rows:
        approx_latitude, approx_longitude = approximate_point(
            event_id, latitude, longitude
        )
        connection.execute(
            event.update()
            .where(event.c.event_id == event_id)
            .values(approx_latitude=approx_latitude, approx_longitude=approx_longitude)
        )

    with op.batch_alter_table("event") as batch_op:
        batch_op.alter_column(
            "approx_latitude", existing_type=sa.Double(), nullable=False
        )
        batch_op.alter_column(
            "approx_longitude", existing_type=sa.Double(), nullable=False
        )
    op.create_index(
        "idx_event_approx_coordinates",
        "event",
        ["approx_latitude", "approx_longitude"],
    )


def downgrade() -> None:
    op.drop_index("idx_event_approx_coordinates", table_name="event")
    with op.batch_alter_table("event") as batch_op:
        batch_op.drop_column("approx_longitude")
        batch_op.drop_column("approx_latitude")
        batch_op.drop_column("location_city")
        batch_op.drop_column("location_neighborhood")
