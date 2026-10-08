"""add_user_block

Revision ID: 20261007_02
Revises: 20261007_01
Create Date: 2026-10-07 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261007_02"
down_revision: str | Sequence[str] | None = "20261007_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_block",
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blocker_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_user_block_not_self"),
    )
    op.create_index(
        "ix_user_block_blocked_id", "user_block", ["blocked_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_user_block_blocked_id", table_name="user_block")
    op.drop_table("user_block")
