"""create_event_favorite

Revision ID: 20261008_01
Revises: 20261012_02
Create Date: 2026-10-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261008_01"
down_revision: str | Sequence[str] | None = "20261012_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_favorite",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["event.event_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "event_id"),
    )
    op.create_index("idx_event_favorite_event_id", "event_favorite", ["event_id"])


def downgrade() -> None:
    op.drop_index("idx_event_favorite_event_id", table_name="event_favorite")
    op.drop_table("event_favorite")
