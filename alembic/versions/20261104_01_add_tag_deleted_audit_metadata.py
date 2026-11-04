"""add_tag_deleted_audit_metadata

Revision ID: 20261104_01
Revises: 20261103_01
Create Date: 2026-11-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261104_01"
down_revision: str | Sequence[str] | None = "20261103_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE auditactionenum ADD VALUE IF NOT EXISTS 'TAG_DELETED'"
            )
    op.add_column("audit_log", sa.Column("metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_log", "metadata")
    # PostgreSQL enum values cannot be removed without rebuilding the type.
    # Keeping TAG_DELETED is safe and avoids rewriting existing audit rows.
