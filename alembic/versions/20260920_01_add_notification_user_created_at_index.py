"""add notification user_id, created_at index

Revision ID: 20260920_01
Revises: 20260916_02
Create Date: 2026-09-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260920_01"
down_revision: str | Sequence[str] | None = "20260916_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_notification_user_id_created_at",
        "notification",
        ["user_id", sa.text("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notification_user_id_created_at", table_name="notification")
