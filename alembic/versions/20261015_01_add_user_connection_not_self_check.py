"""add_user_connection_not_self_check

Revision ID: 20261015_01
Revises: 20261011_01
Create Date: 2026-10-15 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261015_01"
down_revision: str | Sequence[str] | None = "20261011_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The unique pair index already exists (20261007_01); this adds the
    # missing guard against a user connecting to themselves.
    op.create_check_constraint(
        "ck_user_connection_not_self",
        "user_connection",
        "requester_id <> receiver_id",
    )


def downgrade() -> None:
    op.drop_constraint("ck_user_connection_not_self", "user_connection", type_="check")