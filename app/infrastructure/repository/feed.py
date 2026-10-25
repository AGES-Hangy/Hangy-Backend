from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.domain.entities import FeedEvent, Tag
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    EventStatusEnum,
)
from app.infrastructure.repository.block import block_exists_between
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import (
    EventFavoriteModel,
    EventModel,
    EventParticipantModel,
    TagModel,
    event_tag,
    user_tag,
)

# PUBLISHED is the published state of an event: DRAFT is still being written and
# CANCELLED/FINISHED are already over, so only PUBLISHED reaches the feed.
PUBLISHED_EVENT_STATUS = EventStatusEnum.PUBLISHED

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
    ) -> list[FeedEvent]:
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
        viewer_favorited = (
            exists()
            .where(
                EventFavoriteModel.event_id == EventModel.event_id,
                EventFavoriteModel.user_id == viewer_id,
            )
            .correlate(EventModel)
        )
        # Aliased so it does not capture the participant count subquery above.
        viewer_participation = aliased(EventParticipantModel)
        tagged_events = select(event_tag.c.event_id).where(
            event_tag.c.tag_id.in_(tag_ids)
        )
        rows = self.db.execute(
            select(
                EventModel,
                participants_count,
                viewer_participation.status,
                viewer_favorited,
            )
            # Joined here, not fetched per card: a user has at most one
            # participation per event, so the join never multiplies rows.
            .outerjoin(
                viewer_participation,
                and_(
                    viewer_participation.event_id == EventModel.event_id,
                    viewer_participation.user_id == viewer_id,
                ),
            )
            .options(selectinload(EventModel.tags))
            .where(
                EventModel.event_id.in_(tagged_events),
                EventModel.deleted_at.is_(None),
                EventModel.event_status == PUBLISHED_EVENT_STATUS,
                EventModel.starts_at > reference_time,
                EventModel.event_privacy.in_(DISCOVERABLE_PRIVACIES),
                # A block hides both sides from each other, so events created
                # by someone the viewer blocked are dropped too.
                ~block_exists_between(EventModel.event_creator_id, viewer_id),
            )
            .order_by(EventModel.starts_at, EventModel.event_id)
            .limit(limit)
        ).all()
        matched_tag_ids = set(tag_ids)
        return [
            self._to_entity(
                model, count, participation_status, favorited, matched_tag_ids
            )
            for model, count, participation_status, favorited in rows
        ]

    @staticmethod
    def _to_entity(
        model: EventModel,
        participants_count: int,
        viewer_participation_status: EventParticipantStatusEnum | None,
        viewer_favorited: bool,
        matched_tag_ids: set[UUID],
    ) -> FeedEvent:
        return FeedEvent(
            event=SqlAlchemyEventRepository.to_entity(model),
            participants_count=participants_count,
            viewer_participation_status=viewer_participation_status,
            viewer_favorited=bool(viewer_favorited),
            # Only the tag(s) that matched this section — an event tagged
            # `Futebol` and `Rock` shows just `Futebol` under Esportes.
            tags=tuple(
                SqlAlchemyFeedRepository._to_tag_entity(tag)
                for tag in model.tags
                if tag.tag_id in matched_tag_ids
            ),
        )

    @staticmethod
    def _to_tag_entity(model: TagModel) -> Tag:
        return Tag(
            tag_id=model.tag_id,
            tag_name=model.tag_name,
            tag_parent_id=model.tag_parent_id,
        )
