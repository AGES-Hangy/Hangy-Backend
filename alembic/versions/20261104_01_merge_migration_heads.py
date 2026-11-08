"""merge migration heads

Revision ID: 20261104_01
Revises: 20261015_01, 20261103_01
Create Date: 2026-11-04 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "20261104_01"
down_revision: str | Sequence[str] | None = ("20261015_01", "20261103_01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the independent migration branches."""


def downgrade() -> None:
    """Split the independent migration branches."""
