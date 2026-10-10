from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import exists, func, inspect, or_, select
from sqlalchemy.orm import Session

from app.domain.entities import ProfileEvent, UserEvent
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
    UserEventsTabEnum,
)
from app.infrastructure.repository.event_details import (
    USER_BLOCK_TABLE_NAME,
    user_block,
)
from app.infrastructure.repository.models import EventModel, EventParticipantModel


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
        limit: int,
        cursor_starts_at: datetime | None,
        cursor_event_id: UUID | None,
    ) -> list[UserEvent]:
        """List the user's confirmed participations of one profile tab.

        The tab rules mirror `get_profile_counts`, so a list never disagrees
        with the counter shown on its tab.
        """
        now = _now_utc()
        is_over = or_(
            EventModel.event_status == EventStatusEnum.FINISHED,
            EventModel.ends_at <= now,
        )

        stmt = (
            select(EventModel, EventParticipantModel.status)
            .join(
                EventParticipantModel,
                EventParticipantModel.event_id == EventModel.event_id,
            )
            .where(
                EventParticipantModel.user_id == user_id,
                EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
                EventModel.deleted_at.is_(None),
            )
        )

        if tab is UserEventsTabEnum.CONFIRMED:
            stmt = stmt.where(
                EventModel.event_status == EventStatusEnum.PUBLISHED, ~is_over
            ).order_by(EventModel.starts_at.asc(), EventModel.event_id.asc())
            if cursor_starts_at is not None and cursor_event_id is not None:
                stmt = stmt.where(
                    or_(
                        EventModel.starts_at > cursor_starts_at,
                        (EventModel.starts_at == cursor_starts_at)
                        & (EventModel.event_id > cursor_event_id),
                    )
                )
        else:
            stmt = stmt.where(
                EventModel.event_status.in_(
                    (EventStatusEnum.PUBLISHED, EventStatusEnum.FINISHED)
                ),
                is_over,
            ).order_by(EventModel.starts_at.desc(), EventModel.event_id.desc())
            if cursor_starts_at is not None and cursor_event_id is not None:
                stmt = stmt.where(
                    or_(
                        EventModel.starts_at < cursor_starts_at,
                        (EventModel.starts_at == cursor_starts_at)
                        & (EventModel.event_id < cursor_event_id),
                    )
                )

        rows = self.db.execute(stmt.limit(limit)).all()
        return [self._to_entity(event, status) for event, status in rows]

    @staticmethod
    def _to_entity(
        model: EventModel, participation_status: EventParticipantStatusEnum
    ) -> UserEvent:
        return UserEvent(
            event_id=model.event_id,
            title=model.event_title,
            starts_at=model.starts_at,
            participation_status=participation_status,
            location_name=model.location_name,
            cover_photo_url=model.cover_photo_url,
        )

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

    def list_for_profile(
        self,
        user_id: UUID,
        viewer_id: UUID,
        *,
        privacies: Collection[EventPrivacyEnum] | None,
        statuses: Collection[EventStatusEnum] | None,
        limit: int,
        cursor_starts_at: datetime | None,
        cursor_event_id: UUID | None,
    ) -> list[ProfileEvent]:
        """List the events a user created or confirmed presence in.

        A single SELECT over events, so one created by the user who is also a
        participant still comes back only once.
        """
        confirmed_participations = select(EventParticipantModel.event_id).where(
            EventParticipantModel.user_id == user_id,
            EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
        )
        stmt = (
            select(EventModel)
            .where(
                EventModel.deleted_at.is_(None),
                or_(
                    EventModel.event_creator_id == user_id,
                    EventModel.event_id.in_(confirmed_participations),
                ),
            )
            .order_by(EventModel.starts_at.asc(), EventModel.event_id.asc())
        )
        if privacies is not None:
            stmt = stmt.where(EventModel.event_privacy.in_(privacies))
        if statuses is not None:
            stmt = stmt.where(EventModel.event_status.in_(statuses))
        if self._has_user_block_table():
            # Same rule as GET /events/{id}: an organizer who blocked the
            # viewer hides the event, so the card never leads to a 404.
            stmt = stmt.where(
                ~exists().where(
                    user_block.c.blocker_id == EventModel.event_creator_id,
                    user_block.c.blocked_id == viewer_id,
                )
            )
        if cursor_starts_at is not None and cursor_event_id is not None:
            stmt = stmt.where(
                or_(
                    EventModel.starts_at > cursor_starts_at,
                    (EventModel.starts_at == cursor_starts_at)
                    & (EventModel.event_id > cursor_event_id),
                )
            )

        models = self.db.scalars(stmt.limit(limit)).all()
        return [self._to_profile_entity(model) for model in models]

    def _has_user_block_table(self) -> bool:
        """Task 087 owns ``user_block``; until it lands, nobody is blocked."""
        return inspect(self.db.get_bind()).has_table(USER_BLOCK_TABLE_NAME)

    @staticmethod
    def _to_profile_entity(model: EventModel) -> ProfileEvent:
        return ProfileEvent(
            event_id=model.event_id,
            title=model.event_title,
            starts_at=model.starts_at,
            privacy=model.event_privacy,
            location_name=model.location_name,
            cover_photo_url=model.cover_photo_url,
        )
