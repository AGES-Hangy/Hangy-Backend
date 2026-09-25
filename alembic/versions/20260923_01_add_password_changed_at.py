"""add_password_changed_at

Revision ID: 20260923_01
Revises: 20260916_03
Create Date: 2026-09-23 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_01"
down_revision: str | Sequence[str] | None = "20260916_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("password_changed_at", sa.DateTime(timezone=True)))
    op.execute('UPDATE "user" SET password_changed_at = created_at')


def downgrade() -> None:
    op.drop_column("user", "password_changed_at")
