"""upgrade_audit_log

Revision ID: 20261104_05
Revises: 20261104_04
Create Date: 2026-11-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261104_05"
down_revision: str | Sequence[str] | None = "20261104_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_AUDIT_ACTIONS = ("TAG_CREATED",)
NEW_AUDIT_ACTIONS = (
    "USER_BANNED",
    "USER_SUSPENDED",
    "USER_REVERTED",
    "REPORT_ARCHIVED",
    "TAG_CREATED",
    "TAG_UPDATED",
    "TAG_DELETED",
)
AUDIT_ACTION_ENUM = "auditactionenum"
AUDIT_ACTION_ENUM_OLD = "auditactionenum_old"

TARGET_TYPE_ENUM = "audittargettypeenum"
TARGET_TYPES = ("USER", "REPORT", "TAG")


def upgrade() -> None:
    # 20261027_01 (this branch's own table-creation migration) never applied
    # anywhere: PR #118 already created the `audit_log` table in `develop`
    # first, under a minimal schema (TAG_CREATED-only). This migration
    # upgrades that table in place to the full schema instead of creating a
    # second one.

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

    op.alter_column("audit_log", "audit_id", new_column_name="audit_log_id")

    target_type_enum = sa.Enum(*TARGET_TYPES, name=TARGET_TYPE_ENUM)
    target_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "audit_log",
        sa.Column(
            "target_type",
            sa.Enum(*TARGET_TYPES, name=TARGET_TYPE_ENUM, create_type=False),
            nullable=True,
        ),
    )
    # Every pre-existing row came from the old TAG_CREATED-only schema. Plain
    # SQL, not an ORM UPDATE: a bind param would infer VARCHAR and Postgres
    # refuses to assign that to an enum column without an explicit cast.
    op.execute("UPDATE audit_log SET target_type = 'TAG'")
    op.alter_column("audit_log", "target_type", nullable=False)

    op.add_column("audit_log", sa.Column("target_label", sa.String(255)))
    op.add_column("audit_log", sa.Column("metadata", sa.JSON()))
    op.alter_column("audit_log", "target_id", nullable=False)

    op.drop_index("ix_audit_log_action_created_at", table_name="audit_log")
    op.create_index(
        "ix_audit_log_created_at", "audit_log", [sa.text("created_at DESC")]
    )
    op.create_index("ix_audit_log_target_type", "audit_log", ["target_type"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_target_type", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.create_index(
        "ix_audit_log_action_created_at", "audit_log", ["action", "created_at"]
    )

    op.alter_column("audit_log", "target_id", nullable=True)
    op.drop_column("audit_log", "metadata")
    op.drop_column("audit_log", "target_label")

    op.drop_column("audit_log", "target_type")
    sa.Enum(name=TARGET_TYPE_ENUM).drop(op.get_bind(), checkfirst=True)

    op.alter_column("audit_log", "audit_log_id", new_column_name="audit_id")

    op.execute(f"ALTER TYPE {AUDIT_ACTION_ENUM} RENAME TO {AUDIT_ACTION_ENUM_OLD}")
    sa.Enum(*OLD_AUDIT_ACTIONS, name=AUDIT_ACTION_ENUM).create(
        op.get_bind(), checkfirst=False
    )
    op.execute(
        f"ALTER TABLE audit_log ALTER COLUMN action "
        f"TYPE {AUDIT_ACTION_ENUM} USING action::text::{AUDIT_ACTION_ENUM}"
    )
    op.execute(f"DROP TYPE {AUDIT_ACTION_ENUM_OLD}")
