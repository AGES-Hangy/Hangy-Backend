"""add_registration_fields

Revision ID: 20260916_03
Revises: 20260916_02
Create Date: 2026-09-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260916_03"
down_revision: str | Sequence[str] | None = "20260916_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("accepted_terms_at", sa.DateTime(timezone=True)))
    op.add_column("user", sa.Column("accepted_terms_version", sa.String(50)))
    op.drop_constraint("user_email_key", "user", type_="unique")
    op.create_index(
        "uq_user_email_active",
        "user",
        ["email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column(
        "business_profile",
        sa.Column("address", sa.String(255), nullable=False, server_default=""),
    )
    op.alter_column("business_profile", "address", server_default=None)


def downgrade() -> None:
    op.drop_column("business_profile", "address")

    op.drop_index("uq_user_email_active", table_name="user")
    op.create_unique_constraint("user_email_key", "user", ["email"])
    op.drop_column("user", "accepted_terms_version")
    op.drop_column("user", "accepted_terms_at")
