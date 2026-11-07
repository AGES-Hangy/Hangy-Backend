"""add_tag_updated_audit_action

Revision ID: 20261107_01
Revises: 20261105_01
Create Date: 2026-11-07 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261107_01"
down_revision: str | Sequence[str] | None = "20261105_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE auditactionenum ADD VALUE IF NOT EXISTS 'TAG_UPDATED'"
            )


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed without rebuilding the type.
    # Keeping TAG_UPDATED is safe and avoids rewriting existing audit rows.
    pass
