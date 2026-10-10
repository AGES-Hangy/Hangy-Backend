"""create_user_block

Revision ID: 20261008_02
Revises: 20261008_01
Create Date: 2026-10-08 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261008_02"
down_revision: str | Sequence[str] | None = "20261008_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # UserBlockModel is already read by the event, profile and favorite
    # queries, but no revision had created its table yet.
    op.create_table(
        "user_block",
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["blocker_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
    )


def downgrade() -> None:
    op.drop_table("user_block")
