from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.entities import FeedItem, Tag
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
    TagModel,
    event_tag,
    user_tag,
)

# CREATED is the published state of an event: DRAFT is still being written and
# CANCELLED/FINISHED are already over, so only CREATED reaches the feed.
PUBLISHED_EVENT_STATUS = EventStatusEnum.CREATED

# INVITE_ONLY events are reached only through their invite link, so they are
# never discoverable; PRIVATE ones are, and the service hides their details.
DISCOVERABLE_PRIVACIES = (
    EventPrivacyEnum.PUBLIC,
    EventPrivacyEnum.PRIVATE,
)


class SqlAlchemyFeedRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_interest_tags(self, user_id: UUID) -> list[Tag]:
        models = self.db.scalars(
            select(TagModel)
            .join(user_tag, user_tag.c.tag_id == TagModel.tag_id)
            .where(user_tag.c.user_id == user_id)
        ).all()
        return [self._to_tag_entity(model) for model in models]

    def list_tags_by_ids(self, tag_ids: Collection[UUID]) -> list[Tag]:
        if not tag_ids:
            return []
        models = self.db.scalars(
            select(TagModel).where(TagModel.tag_id.in_(tag_ids))
        ).all()
        return [self._to_tag_entity(model) for model in models]

    def list_events_for_tags(
        self,
        viewer_id: UUID,
        tag_ids: Collection[UUID],
        reference_time: datetime,
        limit: int,
    ) -> list[FeedItem]:
        if not tag_ids or limit <= 0:
            return []

        participants_count = (
            select(func.count())
            .select_from(EventParticipantModel)
            .where(
                EventParticipantModel.event_id == EventModel.event_id,
                EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
            )
            .scalar_subquery()
        )
        tagged_events = select(event_tag.c.event_id).where(
            event_tag.c.tag_id.in_(tag_ids)
        )
        rows = self.db.execute(
            select(EventModel, participants_count)
            .where(
                EventModel.event_id.in_(tagged_events),
                EventModel.deleted_at.is_(None),
                EventModel.event_status == PUBLISHED_EVENT_STATUS,
                EventModel.starts_at > reference_time,
                EventModel.event_privacy.in_(DISCOVERABLE_PRIVACIES),
            )
            # TODO(USER_BLOCK): `viewer_id` is kept for the filter that must drop
            # events created by someone who blocked the viewer. The schema has no
            # USER_BLOCK table yet, so there is nothing to join against.
            .order_by(EventModel.starts_at, EventModel.event_id)
            .limit(limit)
        ).all()
        return [self._to_entity(model, count) for model, count in rows]

    @staticmethod
    def _to_entity(model: EventModel, participants_count: int) -> FeedItem:
        return FeedItem(
            event_id=model.event_id,
            title=model.event_title,
            event_date=model.starts_at,
            # EVENT only stores coordinates; there is no venue name column yet.
            location_name=None,
            cover_photo_url=model.cover_photo_url,
            privacy=model.event_privacy,
            participants_count=participants_count,
        )

    @staticmethod
    def _to_tag_entity(model: TagModel) -> Tag:
        return Tag(
            tag_id=model.tag_id,
            tag_name=model.tag_name,
            tag_parent_id=model.tag_parent_id,
        )
