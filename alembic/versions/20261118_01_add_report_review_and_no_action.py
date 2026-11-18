"""add_report_review_and_no_action

Revision ID: 20261118_01
Revises: 20261116_02
Create Date: 2026-11-18 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261118_01"
down_revision: str | Sequence[str] | None = "20261116_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# "Em análise" and "Resolver sem ação" in the report detail.
NEW_ENUM_VALUES = (
    ("reportresolutionactionenum", "NO_ACTION"),
    ("auditactionenum", "REPORT_REVIEWED"),
    ("auditactionenum", "REPORT_RESOLVED"),
)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # ADD VALUE cannot run inside the migration transaction.
        with op.get_context().autocommit_block():
            for enum_name, value in NEW_ENUM_VALUES:
                op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum type; the values stay unused.
    pass
