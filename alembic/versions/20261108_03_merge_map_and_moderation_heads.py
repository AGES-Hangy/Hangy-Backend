"""Merge the map filter and event moderation migration histories."""

revision = "20261108_03"
down_revision = ("20261106_01", "20261108_02")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both parent revisions have already applied their changes."""


def downgrade() -> None:
    """Restore the two parent revisions."""
