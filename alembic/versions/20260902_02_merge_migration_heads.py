"""merge migration heads

Revision ID: 20260902_02
Revises: 20260901_01, 20260902_01
Create Date: 2026-09-02 22:45:00.000000
"""

from collections.abc import Sequence


revision: str = "20260902_02"
down_revision: str | Sequence[str] | None = ("20260901_01", "20260902_01")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the independent migration branches."""


def downgrade() -> None:
    """Split the independent migration branches."""
