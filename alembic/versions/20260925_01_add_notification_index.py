"""add_notification_user_created_at_index

Revision ID: 20260925_01_add_notification_index
Revises: 20260923_01_add_password_changed_at
Create Date: 2026-09-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260925_01"
down_revision: str | None = "20260923_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_notification_user_id_created_at_desc "
        "ON notification (user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX idx_notification_user_id_created_at_desc")
