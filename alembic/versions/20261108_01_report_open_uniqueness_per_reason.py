"""report: one open report per author, target and reason

Replaces the PENDING-only unique indexes (one per author and target) with
indexes that include report_type and cover PENDING and REVIEWED.

It also merges the two heads that develop had (20261104_05 and 20261105_02,
both children of 20261105_01) so the migration graph keeps a single head.

Revision ID: 20261108_01
Revises: 20261104_05, 20261105_02
Create Date: 2026-11-08 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261108_01"
down_revision: str | Sequence[str] | None = ("20261104_05", "20261105_02")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OPEN = "status IN ('PENDING', 'REVIEWED')"


def _assert_no_open_duplicates() -> None:
    """Fail with a readable message if rows would break the new indexes.

    The old indexes only covered PENDING, so REVIEWED rows may already repeat.
    Nothing is rewritten here: those reports need a decision from moderation.
    """
    connection = op.get_bind()
    for target in ("reported_user_id", "reported_event_id"):
        duplicates = connection.scalar(
            sa.text(
                f"SELECT count(*) FROM (SELECT 1 FROM report "
                f"WHERE {_OPEN} AND {target} IS NOT NULL "
                f"GROUP BY report_creator_id, {target}, report_type "
                f"HAVING count(*) > 1) AS d"
            )
        )
        if duplicates:
            raise RuntimeError(
                f"{duplicates} author/{target}/report_type groups have more than "
                "one PENDING/REVIEWED report. Resolve or reject the extra "
                "reports before applying this migration."
            )


def upgrade() -> None:
    _assert_no_open_duplicates()
    op.drop_index("uq_report_pending_event", table_name="report")
    op.drop_index("uq_report_pending_user", table_name="report")
    op.create_index(
        "uq_report_open_user_type",
        "report",
        ["report_creator_id", "reported_user_id", "report_type"],
        unique=True,
        postgresql_where=sa.text(f"{_OPEN} AND reported_user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_report_open_event_type",
        "report",
        ["report_creator_id", "reported_event_id", "report_type"],
        unique=True,
        postgresql_where=sa.text(f"{_OPEN} AND reported_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Fails if an author has open reports with different reasons for one target."""
    op.drop_index("uq_report_open_event_type", table_name="report")
    op.drop_index("uq_report_open_user_type", table_name="report")
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
