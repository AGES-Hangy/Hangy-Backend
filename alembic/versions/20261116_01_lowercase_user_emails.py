"""user: store emails lower-cased

The API now lower-cases every email it receives and compares emails with
lower(). This lower-cases the rows written before that, except when two active
accounts differ only by case: those are left as they are (lookups still find
one of them) and must be merged by hand.

Revision ID: 20261116_01
Revises: 20261109_01
Create Date: 2026-11-16 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261116_01"
down_revision: str | Sequence[str] | None = "20261109_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE "user" AS u
            SET email = lower(u.email)
            WHERE u.email <> lower(u.email)
              AND NOT EXISTS (
                SELECT 1 FROM "user" AS other
                WHERE other.user_id <> u.user_id
                  AND other.deleted_at IS NULL
                  AND lower(other.email) = lower(u.email)
              )
            """
        )
    )


def downgrade() -> None:
    """The original casing is not kept, so there is nothing to restore."""
