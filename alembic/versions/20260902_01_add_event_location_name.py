"""add_event_location_name_and_publish_status

Revision ID: 20260902_01
Revises: 20260826_01
Create Date: 2026-09-02 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260902_01"
down_revision: str | Sequence[str] | None = "20260826_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("event", sa.Column("location_name", sa.String(120), nullable=True))
    # Renaming the value keeps every existing row valid, unlike recreating the type.
    op.execute("ALTER TYPE eventstatusenum RENAME VALUE 'CREATED' TO 'PUBLISHED'")


def downgrade() -> None:
    op.execute("ALTER TYPE eventstatusenum RENAME VALUE 'PUBLISHED' TO 'CREATED'")
    op.drop_column("event", "location_name")
