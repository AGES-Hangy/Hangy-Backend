"""add unique constraint for event experience participant

Revision ID: 20261012_01
Revises: 20261007_01
Create Date: 2026-10-12 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261012_01"
down_revision: str | Sequence[str] | None = "20261007_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_event_experience_participant",
        "event_experience",
        ["event_participant_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_event_experience_participant", "event_experience", type_="unique"
    )
