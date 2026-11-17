"""merge search and moderation heads

Revision ID: 20261104_03
Revises: 20261028_01, 20261104_02
Create Date: 2026-11-04 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "20261104_03"
down_revision: str | Sequence[str] | None = ("20261028_01", "20261104_02")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the independent migration branches."""


def downgrade() -> None:
    """Split the independent migration branches."""
