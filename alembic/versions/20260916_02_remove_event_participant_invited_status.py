"""remove_event_participant_invited_status

Revision ID: 20260916_02
Revises: 20260916_01
Create Date: 2026-09-16 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260916_02"
down_revision: str | Sequence[str] | None = "20260916_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_VALUES = (
    "INVITED",
    "PENDING",
    "CONFIRMED",
    "REJECTED",
    "CANCELLED",
    "REMOVED",
)

NEW_VALUES = (
    "PENDING",
    "CONFIRMED",
    "REJECTED",
    "CANCELLED",
    "REMOVED",
)

ENUM_NAME = "eventparticipantstatusenum"
OLD_ENUM_NAME = "eventparticipantstatusenum_old"


def upgrade() -> None:
    # Postgres enums have no DROP VALUE. INVITED was the pending state for the
    # old in-app, user-to-user invite - joining is link-only now and always
    # lands straight on PENDING/CONFIRMED, so the type is swapped without it.
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {OLD_ENUM_NAME}")
    sa.Enum(*NEW_VALUES, name=ENUM_NAME).create(op.get_bind(), checkfirst=False)
    op.execute(
        f"ALTER TABLE event_participant ALTER COLUMN status TYPE {ENUM_NAME} "
        f"USING status::text::{ENUM_NAME}"
    )
    op.execute(f"DROP TYPE {OLD_ENUM_NAME}")


def downgrade() -> None:
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {OLD_ENUM_NAME}")
    sa.Enum(*OLD_VALUES, name=ENUM_NAME).create(op.get_bind(), checkfirst=False)
    op.execute(
        f"ALTER TABLE event_participant ALTER COLUMN status TYPE {ENUM_NAME} "
        f"USING status::text::{ENUM_NAME}"
    )
    op.execute(f"DROP TYPE {OLD_ENUM_NAME}")
