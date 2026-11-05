"""report exclusive target check and pending uniqueness

Revision ID: 20261105_02
Revises: 20261105_01
Create Date: 2026-11-05 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261105_02"
down_revision: str | Sequence[str] | None = "20261105_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_report_exactly_one_target",
        "report",
        "(reported_user_id IS NULL) <> (reported_event_id IS NULL)",
    )
    op.create_index(
        "uq_report_pending_user",
        "report",
        ["report_creator_id", "reported_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING' AND reported_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_report_pending_event",
        "report",
        ["report_creator_id", "reported_event_id"],
        unique=True,
        postgresql_where=sa.text(
            "status = 'PENDING' AND reported_event_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_report_pending_event", table_name="report")
    op.drop_index("uq_report_pending_user", table_name="report")
    op.drop_constraint("ck_report_exactly_one_target", "report", type_="check")
