"""merge migration heads

Revision ID: 20260927_01
Revises: 20260920_01, 20260923_01
Create Date: 2026-09-27 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "20260927_01"
down_revision: str | Sequence[str] | None = ("20260920_01", "20260923_01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the independent migration branches."""


def downgrade() -> None:
    """Split the independent migration branches."""
