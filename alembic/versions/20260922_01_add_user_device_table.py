"""add_user_device_table

Revision ID: 20260922_01
Revises: 20260916_02
Create Date: 2026-09-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260922_01"
down_revision: str | Sequence[str] | None = "20260916_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PLATFORM_VALUES = ("ANDROID", "IOS")
ENUM_NAME = "deviceplatformenum"
ENUM_VALUES_SQL = ", ".join(repr(v) for v in PLATFORM_VALUES)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE {ENUM_NAME} AS ENUM ({ENUM_VALUES_SQL});
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
        """
    )
    op.create_table(
        "user_device",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_token", sa.String(512), nullable=False),
        sa.Column(
            "platform",
            postgresql.ENUM(*PLATFORM_VALUES, name=ENUM_NAME, create_type=False),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.user_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
        sa.UniqueConstraint("device_token"),
    )


def downgrade() -> None:
    op.drop_table("user_device")
    op.execute(f"DROP TYPE IF EXISTS {ENUM_NAME}")
