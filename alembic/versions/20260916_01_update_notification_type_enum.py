"""update_notification_type_enum

Revision ID: 20260916_01
Revises: 20260909_01
Create Date: 2026-09-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260916_01"
down_revision: str | Sequence[str] | None = "20260909_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_VALUES = (
    "CONNECTION_REQUEST",
    "EVENT_INVITE",
    "EVENT_PARTICIPATION_REQUEST",
    "EVENT_REQUEST_APPROVED",
    "EVENT_REQUEST_REJECTED",
    "EVENT_PARTICIPANT_CANCELLED",
    "EVENT_PARTICIPANT_REMOVED",
    "EVENT_CANCELLED",
)

NEW_VALUES = (
    "CONNECTION_REQUEST",
    "CONNECTION_ACCEPTED",
    "EVENT_PARTICIPATION_REQUEST",
    "EVENT_REQUEST_APPROVED",
    "EVENT_REQUEST_REJECTED",
    "EVENT_PARTICIPANT_CANCELLED",
    "EVENT_PARTICIPANT_REMOVED",
    "EVENT_PARTICIPANT_JOINED",
    "EVENT_UPDATED",
    "EVENT_CANCELLED",
    "EVENT_STARTING_SOON",
)

ENUM_NAME = "notificationtypeenum"
OLD_ENUM_NAME = "notificationtypeenum_old"


def upgrade() -> None:
    # Postgres enums have no DROP VALUE, so dropping EVENT_INVITE (there is no
    # more in-app, user-to-user invite - joining by invite is link-only now)
    # means swapping in a whole new type rather than just adding values.
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {OLD_ENUM_NAME}")
    sa.Enum(*NEW_VALUES, name=ENUM_NAME).create(op.get_bind(), checkfirst=False)
    op.execute(
        f"ALTER TABLE notification ALTER COLUMN type TYPE {ENUM_NAME} "
        f"USING type::text::{ENUM_NAME}"
    )
    op.execute(f"DROP TYPE {OLD_ENUM_NAME}")


def downgrade() -> None:
    op.execute(f"ALTER TYPE {ENUM_NAME} RENAME TO {OLD_ENUM_NAME}")
    sa.Enum(*OLD_VALUES, name=ENUM_NAME).create(op.get_bind(), checkfirst=False)
    op.execute(
        f"ALTER TABLE notification ALTER COLUMN type TYPE {ENUM_NAME} "
        f"USING type::text::{ENUM_NAME}"
    )
    op.execute(f"DROP TYPE {OLD_ENUM_NAME}")
