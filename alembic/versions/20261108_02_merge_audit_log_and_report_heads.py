"""Merge audit log and report constraint heads.

Revision ID: 20261108_02
Revises: 20261104_05, 20261105_02
"""

from collections.abc import Sequence

revision: str = "20261108_02"
down_revision: tuple[str, str] = ("20261104_05", "20261105_02")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join the two revisions without changing the schema."""


def downgrade() -> None:
    """Restore the two parent revisions."""
