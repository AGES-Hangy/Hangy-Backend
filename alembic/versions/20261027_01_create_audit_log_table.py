"""create_audit_log_table

Revision ID: 20261027_01
Revises: 20261015_01
Create Date: 2026-10-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_01"
down_revision: str | Sequence[str] | None = "20261015_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_TYPES = (
    "auditactionenum",
    "audittargettypeenum",
)


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("audit_log_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column(
            "action",
            sa.Enum(
                "USER_BANNED",
                "USER_SUSPENDED",
                "USER_REVERTED",
                "REPORT_ARCHIVED",
                "TAG_CREATED",
                "TAG_UPDATED",
                "TAG_DELETED",
                name="auditactionenum",
            ),
            nullable=False,
        ),
        sa.Column(
            "target_type",
            sa.Enum("USER", "REPORT", "TAG", name="audittargettypeenum"),
            nullable=False,
        ),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("target_label", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["user.user_id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("audit_log_id"),
    )
    op.create_index(
        "ix_audit_log_created_at", "audit_log", [sa.text("created_at DESC")]
    )
    op.create_index("ix_audit_log_target_type", "audit_log", ["target_type"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_target_type", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    for enum_name in ENUM_TYPES:
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
