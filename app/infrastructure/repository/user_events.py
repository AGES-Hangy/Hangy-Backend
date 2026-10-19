from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.domain.entities import UserEventParticipation
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserEventsTabEnum,
)
from app.infrastructure.repository.block import block_exists_between
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import (
    EventFavoriteModel,
    EventModel,
    EventParticipantModel,
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


class SqlAlchemyUserEventsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(
        self,
        user_id: UUID,
        tab: UserEventsTabEnum,
        *,
        viewer_id: UUID,
        public_only: bool,
        limit: int,
        cursor_starts_at: datetime | None,
        cursor_event_id: UUID | None,
    ) -> list[UserEventParticipation]:
        """List one profile tab of `user_id` as `viewer_id` may see it.

        Each tab is a single SELECT over events, so an event the user both
        created and attends comes back once. The `history` and `confirmed`
        rules mirror `get_profile_counts`, so a list never disagrees with the
        counter shown on its tab.
        """
        now = _now_utc()
        is_over = or_(
            EventModel.event_status == EventStatusEnum.FINISHED,
            EventModel.ends_at <= now,
        )
        is_confirmed = (
            exists()
            .where(
                EventParticipantModel.event_id == EventModel.event_id,
                EventParticipantModel.user_id == user_id,
                EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
            )
            .correlate(EventModel)
        )

        stmt = select(EventModel, is_confirmed.label("is_confirmed")).where(
            EventModel.deleted_at.is_(None),
            # Same rule as the feed: a block hides both sides from each other,
            # so events created by someone the viewer blocked are dropped too.
            ~block_exists_between(EventModel.event_creator_id, viewer_id),
        )
        if public_only:
            stmt = stmt.where(EventModel.event_privacy == EventPrivacyEnum.PUBLIC)

        # CANCELLED is in none of the status lists below: it never shows up.
        newest_first = False
        if tab is UserEventsTabEnum.HISTORY:
            newest_first = True
            stmt = stmt.where(
                is_over,
                EventModel.event_status.in_(
                    (EventStatusEnum.PUBLISHED, EventStatusEnum.FINISHED)
                ),
                or_(EventModel.event_creator_id == user_id, is_confirmed),
            )
        elif tab is UserEventsTabEnum.CREATED:
            # A draft is only ever shown to its own organizer.
            statuses = (
                (EventStatusEnum.PUBLISHED,)
                if public_only
                else (EventStatusEnum.PUBLISHED, EventStatusEnum.DRAFT)
            )
            stmt = stmt.where(
                EventModel.event_creator_id == user_id,
                ~is_over,
                EventModel.event_status.in_(statuses),
            )
        elif tab is UserEventsTabEnum.INTERESTS:
            is_favorited = (
                exists()
                .where(
                    EventFavoriteModel.event_id == EventModel.event_id,
                    EventFavoriteModel.user_id == user_id,
                )
                .correlate(EventModel)
            )
            # Visibility is resolved on read: a favorite whose event turned
            # invite-only stays stored, it just stops being listed.
            stmt = stmt.where(
                is_favorited,
                ~is_over,
                EventModel.event_status == EventStatusEnum.PUBLISHED,
                or_(
                    EventModel.event_privacy != EventPrivacyEnum.INVITE_ONLY,
                    EventModel.event_creator_id == user_id,
                    is_confirmed,
                ),
            )
        else:
            stmt = stmt.where(
                is_confirmed,
                ~is_over,
                EventModel.event_status == EventStatusEnum.PUBLISHED,
            )

        if newest_first:
            stmt = stmt.order_by(
                EventModel.starts_at.desc(), EventModel.event_id.desc()
            )
            if cursor_starts_at is not None and cursor_event_id is not None:
                stmt = stmt.where(
                    or_(
                        EventModel.starts_at < cursor_starts_at,
                        (EventModel.starts_at == cursor_starts_at)
                        & (EventModel.event_id < cursor_event_id),
                    )
                )
        else:
            stmt = stmt.order_by(EventModel.starts_at.asc(), EventModel.event_id.asc())
            if cursor_starts_at is not None and cursor_event_id is not None:
                stmt = stmt.where(
                    or_(
                        EventModel.starts_at > cursor_starts_at,
                        (EventModel.starts_at == cursor_starts_at)
                        & (EventModel.event_id > cursor_event_id),
                    )
                )

        rows = self.db.execute(stmt.limit(limit)).all()
        return [self._to_entity(event, confirmed) for event, confirmed in rows]

    @staticmethod
    def _to_entity(model: EventModel, is_confirmed: bool) -> UserEventParticipation:
        return UserEventParticipation(
            event=SqlAlchemyEventRepository.to_entity(model),
            participation_status=(
                EventParticipantStatusEnum.CONFIRMED if is_confirmed else None
            ),
        )
