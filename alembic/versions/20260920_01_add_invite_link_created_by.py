"""add creator to event invite links

Revision ID: 20260920_01
Revises: 20260902_02
Create Date: 2026-09-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260920_01"
down_revision: str | Sequence[str] | None = "20260902_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_invite_link", sa.Column("created_by", sa.UUID(), nullable=True)
    )
    op.execute(
        """
        UPDATE event_invite_link
        SET created_by = event.event_creator_id
        FROM event
        WHERE event_invite_link.event_id = event.event_id
        """
    )
    op.alter_column("event_invite_link", "created_by", nullable=False)
    op.create_foreign_key(
        "fk_event_invite_link_created_by_user",
        "event_invite_link",
        "user",
        ["created_by"],
        ["user_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_event_invite_link_created_by_user", "event_invite_link", type_="foreignkey"
    )
    op.drop_column("event_invite_link", "created_by")
