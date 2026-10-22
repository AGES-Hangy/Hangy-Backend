"""add idx_user_follows_followed_business_id

Revision ID: 20261019_01
Revises: 20261011_01
Create Date: 2026-10-19 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261019_01"
down_revision: str | Sequence[str] | None = "20261011_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_user_follows_followed_business_id",
        "user_follows",
        ["followed_business_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_user_follows_followed_business_id",
        table_name="user_follows",
    )
