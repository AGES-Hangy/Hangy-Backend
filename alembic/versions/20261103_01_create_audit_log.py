"""create_audit_log

Revision ID: 20261103_01
Revises: 20261015_01
Create Date: 2026-11-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_01"
down_revision: str | Sequence[str] | None = "20261019_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column(
            "action", sa.Enum("TAG_CREATED", name="auditactionenum"), nullable=False
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["user.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_audit_log_action_created_at", "audit_log", ["action", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_action_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    sa.Enum(name="auditactionenum").drop(op.get_bind(), checkfirst=True)
