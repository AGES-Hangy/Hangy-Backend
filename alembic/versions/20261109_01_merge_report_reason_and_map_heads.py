"""Merge report reason uniqueness and map/moderation migration heads."""

revision = "20261109_01"
down_revision = ("20261108_01", "20261108_03")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both parent revisions have already applied their changes."""


def downgrade() -> None:
    """Restore the two parent revisions."""
