"""add_search_text_indexes

Revision ID: 20261028_01
Revises: 20261015_01
Create Date: 2026-10-28 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261028_01"
down_revision: str | Sequence[str] | None = "20261015_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        op.create_index(
            "idx_event_title_trgm",
            "event",
            ["event_title"],
            unique=False,
            postgresql_using="gin",
            postgresql_ops={"event_title": "gin_trgm_ops"},
        )
        op.create_index(
            "idx_user_name_trgm",
            "user",
            ["name"],
            unique=False,
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        )
    else:
        op.create_index("idx_event_title_trgm", "event", ["event_title"], unique=False)
        op.create_index("idx_user_name_trgm", "user", ["name"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_user_name_trgm", table_name="user")
    op.drop_index("idx_event_title_trgm", table_name="event")

