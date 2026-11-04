"""add_report_number_and_created_at

Revision ID: 20261104_04
Revises: 20261104_03
Create Date: 2026-11-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261104_04"
down_revision: str | Sequence[str] | None = "20261104_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "report",
        sa.Column("report_number", sa.Integer(), sa.Identity(), nullable=False),
    )
    op.create_unique_constraint("uq_report_report_number", "report", ["report_number"])

    # updated_at moves on every status change, so it cannot order the queue or
    # tell when a report was opened. Existing rows only have updated_at to go on.
    op.add_column(
        "report", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE report SET created_at = updated_at")
    op.alter_column(
        "report", "created_at", nullable=False, server_default=sa.func.now()
    )


def downgrade() -> None:
    op.drop_column("report", "created_at")
    op.drop_constraint("uq_report_report_number", "report", type_="unique")
    op.drop_column("report", "report_number")
