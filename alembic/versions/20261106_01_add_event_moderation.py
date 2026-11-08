"""add_event_moderation

Revision ID: 20261106_01
Revises: 20261104_05
Create Date: 2026-11-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261106_01"
down_revision: str | Sequence[str] | None = "20261104_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODERATION_STATUS_ENUM = "eventmoderationstatusenum"
MODERATION_STATUSES = ("ACTIVE", "REMOVED")

# Existing Postgres enum types that gain an EVENT_REMOVED / EVENT value.
NEW_ENUM_VALUES = (
    ("reportresolutionactionenum", "EVENT_REMOVED"),
    ("auditactionenum", "EVENT_REMOVED"),
    ("audittargettypeenum", "EVENT"),
    ("notificationtypeenum", "EVENT_REMOVED"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # ADD VALUE cannot run inside the migration transaction. The new values
        # are not used here, so no commit is needed before using them.
        with op.get_context().autocommit_block():
            for enum_name, value in NEW_ENUM_VALUES:
                op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")

    sa.Enum(*MODERATION_STATUSES, name=MODERATION_STATUS_ENUM).create(
        bind, checkfirst=True
    )
    op.add_column(
        "event",
        sa.Column(
            "moderation_status",
            sa.Enum(
                *MODERATION_STATUSES, name=MODERATION_STATUS_ENUM, create_type=False
            ),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.add_column(
        "event", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("event", "removed_at")
    op.drop_column("event", "moderation_status")
    sa.Enum(name=MODERATION_STATUS_ENUM).drop(op.get_bind(), checkfirst=True)
    # PostgreSQL enum values cannot be removed without rebuilding each type.
    # Keeping EVENT_REMOVED / EVENT is harmless and avoids rewriting audit,
    # report and notification rows that may already use them.
