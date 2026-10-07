import base64
from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, inspect, or_, select
from sqlalchemy.orm import Session

from app.domain.entities import UserEvent, UserEventsPage
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)
from app.infrastructure.repository.event_details import (
    USER_BLOCK_TABLE_NAME,
    user_block,
)
from app.infrastructure.repository.models import EventModel, EventParticipantModel


class SqlAlchemyUserEventsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def user_blocked_viewer(self, user_id: UUID, viewer_id: UUID) -> bool:
        if not self._has_user_block_table():
            return False

        return (
            self.db.scalar(
                select(func.count())
                .select_from(user_block)
                .where(
                    user_block.c.blocker_id == user_id,
                    user_block.c.blocked_id == viewer_id,
                )
            )
            > 0
        )

    def list_events(
        self,
        user_id: UUID,
        viewer_id: UUID,
        privacies: Collection[EventPrivacyEnum] | None,
        statuses: Collection[EventStatusEnum] | None,
        limit: int,
        cursor: str | None,
    ) -> UserEventsPage:
        confirmed_participations = select(EventParticipantModel.event_id).where(
            EventParticipantModel.user_id == user_id,
            EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
        )
        # A single SELECT over events: one created by the user who is also a
        # participant still comes back only once.
        query = (
            select(EventModel)
            .where(
                EventModel.deleted_at.is_(None),
                or_(
                    EventModel.event_creator_id == user_id,
                    EventModel.event_id.in_(confirmed_participations),
                ),
            )
            .order_by(EventModel.starts_at, EventModel.event_id)
        )
        if privacies is not None:
            query = query.where(EventModel.event_privacy.in_(privacies))
        if statuses is not None:
            query = query.where(EventModel.event_status.in_(statuses))
        if self._has_user_block_table():
            # Same rule as GET /events/{id}: an organizer who blocked the
            # viewer hides the event, so the card never leads to a 404.
            query = query.where(
                ~exists().where(
                    user_block.c.blocker_id == EventModel.event_creator_id,
                    user_block.c.blocked_id == viewer_id,
                )
            )
        if cursor is not None:
            cursor_starts_at, cursor_event_id = self._decode_cursor(cursor)
            if cursor_starts_at is not None:
                query = query.where(
                    or_(
                        EventModel.starts_at > cursor_starts_at,
                        and_(
                            EventModel.starts_at == cursor_starts_at,
                            EventModel.event_id > cursor_event_id,
                        ),
                    )
                )

        models = self.db.scalars(query.limit(limit + 1)).all()
        has_more = len(models) > limit
        page_models = models[:limit]

        next_cursor = None
        if has_more and page_models:
            last = page_models[-1]
            next_cursor = self._encode_cursor(last.starts_at, last.event_id)

        return UserEventsPage(
            items=tuple(self._to_entity(model) for model in page_models),
            next_cursor=next_cursor,
        )

    def _has_user_block_table(self) -> bool:
        """Task 087 owns ``user_block``; until it lands, nobody is blocked."""
        return inspect(self.db.get_bind()).has_table(USER_BLOCK_TABLE_NAME)

    @staticmethod
    def _encode_cursor(starts_at: datetime, event_id: UUID) -> str:
        raw = f"{starts_at.isoformat()}|{event_id}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime | None, UUID | None]:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode()).decode()
            starts_at_raw, event_id_raw = raw.split("|", 1)
            return datetime.fromisoformat(starts_at_raw), UUID(event_id_raw)
        except (ValueError, UnicodeDecodeError):
            # A malformed cursor just restarts the listing from the beginning
            # instead of failing the request.
            return None, None

    @staticmethod
    def _to_entity(model: EventModel) -> UserEvent:
        return UserEvent(
            event_id=model.event_id,
            title=model.event_title,
            event_date=model.starts_at,
            privacy=model.event_privacy,
            location_name=model.location_name,
            cover_photo_url=model.cover_photo_url,
        )
