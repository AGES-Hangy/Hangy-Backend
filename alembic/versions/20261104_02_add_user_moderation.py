"""add_user_moderation

Revision ID: 20261104_02
Revises: 20261104_01
Create Date: 2026-11-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261104_02"
down_revision: str | Sequence[str] | None = "20261104_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_AUDIT_ACTIONS = ("TAG_CREATED",)
NEW_AUDIT_ACTIONS = (
    "TAG_CREATED",
    "USER_BANNED",
    "USER_SUSPENDED",
    "USER_REVERTED",
)
AUDIT_ACTION_ENUM = "auditactionenum"
AUDIT_ACTION_ENUM_OLD = "auditactionenum_old"

RESOLUTION_ACTION_ENUM = "reportresolutionactionenum"
RESOLUTION_ACTIONS = ("BANNED", "SUSPENDED", "ARCHIVED")


def upgrade() -> None:
    op.add_column("user", sa.Column("banned_at", sa.DateTime(timezone=True)))
    op.add_column("user", sa.Column("suspended_until", sa.DateTime(timezone=True)))

    # Postgres enums have no ADD VALUE that is safe to run and use in the same
    # transaction, so this swaps in a whole new type (same approach as
    # 20260916_01_update_notification_type_enum).
    op.execute(f"ALTER TYPE {AUDIT_ACTION_ENUM} RENAME TO {AUDIT_ACTION_ENUM_OLD}")
    sa.Enum(*NEW_AUDIT_ACTIONS, name=AUDIT_ACTION_ENUM).create(
        op.get_bind(), checkfirst=False
    )
    op.execute(
        f"ALTER TABLE audit_log ALTER COLUMN action "
        f"TYPE {AUDIT_ACTION_ENUM} USING action::text::{AUDIT_ACTION_ENUM}"
    )
    op.execute(f"DROP TYPE {AUDIT_ACTION_ENUM_OLD}")

    resolution_action_enum = sa.Enum(*RESOLUTION_ACTIONS, name=RESOLUTION_ACTION_ENUM)
    resolution_action_enum.create(op.get_bind(), checkfirst=True)
    op.add_column("report", sa.Column("resolved_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_report_resolved_by_id_user",
        "report",
        "user",
        ["resolved_by_id"],
        ["user_id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "report", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "report",
        sa.Column(
            "resolution_action",
            sa.Enum(
                *RESOLUTION_ACTIONS, name=RESOLUTION_ACTION_ENUM, create_type=False
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("report", "resolution_action")
    op.drop_column("report", "resolved_at")
    op.drop_constraint("fk_report_resolved_by_id_user", "report", type_="foreignkey")
    op.drop_column("report", "resolved_by_id")
    sa.Enum(name=RESOLUTION_ACTION_ENUM).drop(op.get_bind(), checkfirst=True)

    op.execute(f"ALTER TYPE {AUDIT_ACTION_ENUM} RENAME TO {AUDIT_ACTION_ENUM_OLD}")
    sa.Enum(*OLD_AUDIT_ACTIONS, name=AUDIT_ACTION_ENUM).create(
        op.get_bind(), checkfirst=False
    )
    op.execute(
        f"ALTER TABLE audit_log ALTER COLUMN action "
        f"TYPE {AUDIT_ACTION_ENUM} USING action::text::{AUDIT_ACTION_ENUM}"
    )
    op.execute(f"DROP TYPE {AUDIT_ACTION_ENUM_OLD}")

    op.drop_column("user", "suspended_until")
    op.drop_column("user", "banned_at")
