"""add_user_connection_unique_index

Revision ID: 20261007_01
Revises: 20260928_02
Create Date: 2026-10-07 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261007_01"
down_revision: str | Sequence[str] | None = "20260928_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # LEAST/GREATEST normalize the pair regardless of who is requester vs.
    # receiver, so A->B and B->A can never coexist. Partial on deleted_at
    # IS NULL so undoing a connection (which soft-deletes it) frees the pair
    # for a new request.
    op.execute(
        "CREATE UNIQUE INDEX uq_user_connection_active_pair "
        "ON user_connection (LEAST(requester_id, receiver_id), "
        "GREATEST(requester_id, receiver_id)) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX uq_user_connection_active_pair")
