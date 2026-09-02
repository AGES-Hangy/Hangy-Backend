"""add index on tag parent_id

Revision ID: 20260901_01
Revises: 20260826_01
Create Date: 2026-09-01 22:33:47.949098
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260901_01"
down_revision: str | Sequence[str] | None = "20260901_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_tag_tag_parent_id", "tag", ["tag_parent_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tag_tag_parent_id", table_name="tag")
