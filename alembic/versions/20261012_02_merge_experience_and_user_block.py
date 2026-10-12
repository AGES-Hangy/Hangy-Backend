"""merge experience and user block migration heads

Revision ID: 20261012_02
Revises: 20261007_02, 20261012_01
Create Date: 2026-10-12 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "20261012_02"
down_revision: str | Sequence[str] | None = ("20261007_02", "20261012_01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the independent migration branches."""


def downgrade() -> None:
    """Split the independent migration branches."""
