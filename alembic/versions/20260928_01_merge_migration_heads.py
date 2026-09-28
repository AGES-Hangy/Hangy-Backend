"""merge migration heads

Revision ID: 20260928_01
Revises: 20260922_01, 20260927_02
Create Date: 2026-09-28 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "20260928_01"
down_revision: str | Sequence[str] | None = ("20260922_01", "20260927_02")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the independent migration branches."""


def downgrade() -> None:
    """Split the independent migration branches."""
