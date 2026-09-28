"""remove_person_profile_country

Revision ID: 20260927_02
Revises: 20260927_01
Create Date: 2026-09-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260927_02"
down_revision: str | Sequence[str] | None = "20260927_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("person_profile", "country")


def downgrade() -> None:
    op.add_column(
        "person_profile",
        sa.Column("country", sa.String(100), nullable=False, server_default=""),
    )
    op.alter_column("person_profile", "country", server_default=None)
