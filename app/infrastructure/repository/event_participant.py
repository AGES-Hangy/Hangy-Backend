import base64
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities import (
    Event,
    EventParticipantCounts,
    EventParticipantListItem,
    EventParticipantsPage,
)
from app.domain.enums import EventParticipantStatusEnum
from app.infrastructure.repository.models import EventModel, EventParticipantModel


class SqlAlchemyEventParticipantsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_event(self, event_id: UUID) -> Event | None:
        model = self.db.scalar(
            select(EventModel).where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
        )
        return self._to_event_entity(model) if model is not None else None

    def get_viewer_status(
        self, event_id: UUID, viewer_id: UUID
    ) -> EventParticipantStatusEnum | None:
        return self.db.scalar(
            select(EventParticipantModel.status).where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.user_id == viewer_id,
            )
        )

    def list_participants(
        self,
        event_id: UUID,
        status: EventParticipantStatusEnum,
        limit: int,
        cursor: str | None,
        include_pending_count: bool,
    ) -> EventParticipantsPage:
        confirmed_count = self._count(event_id, EventParticipantStatusEnum.CONFIRMED)
        pending_count = (
            self._count(event_id, EventParticipantStatusEnum.PENDING)
            if include_pending_count
            else None
        )

        query = (
            select(EventParticipantModel)
            .where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.status == status,
            )
            .options(joinedload(EventParticipantModel.user))
            .order_by(
                EventParticipantModel.joined_at, EventParticipantModel.participant_id
            )
        )
        if cursor is not None:
            cursor_joined_at, cursor_participant_id = self._decode_cursor(cursor)
            if cursor_joined_at is not None:
                query = query.where(
                    or_(
                        EventParticipantModel.joined_at > cursor_joined_at,
                        and_(
                            EventParticipantModel.joined_at == cursor_joined_at,
                            EventParticipantModel.participant_id
                            > cursor_participant_id,
                        ),
                    )
                )

        models = self.db.scalars(query.limit(limit + 1)).all()
        has_more = len(models) > limit
        page_models = models[:limit]

        next_cursor = None
        if has_more and page_models:
            last = page_models[-1]
            next_cursor = self._encode_cursor(last.joined_at, last.participant_id)

        return EventParticipantsPage(
            items=tuple(self._to_item_entity(model) for model in page_models),
            counts=EventParticipantCounts(
                confirmed=confirmed_count or 0, pending=pending_count
            ),
            next_cursor=next_cursor,
        )

    def _count(self, event_id: UUID, status: EventParticipantStatusEnum) -> int:
        return (
            self.db.scalar(
                select(func.count(EventParticipantModel.participant_id)).where(
                    EventParticipantModel.event_id == event_id,
                    EventParticipantModel.status == status,
                )
            )
            or 0
        )

    @staticmethod
    def _encode_cursor(joined_at: datetime, participant_id: UUID) -> str:
        raw = f"{joined_at.isoformat()}|{participant_id}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime | None, UUID | None]:
        try:
            raw = base64.urlsafe_b64decode(cursor.encode()).decode()
            joined_at_raw, participant_id_raw = raw.split("|", 1)
            return datetime.fromisoformat(joined_at_raw), UUID(participant_id_raw)
        except (ValueError, UnicodeDecodeError):
            # A malformed cursor just restarts the listing from the beginning
            # instead of failing the request.
            return None, None

    @staticmethod
    def _to_item_entity(model: EventParticipantModel) -> EventParticipantListItem:
        return EventParticipantListItem(
            participant_id=model.participant_id,
            user_id=model.user_id,
            user_name=model.user.name,
            status=model.status,
            joined_at=model.joined_at,
        )

    @staticmethod
    def _to_event_entity(model: EventModel) -> Event:
        return Event(
            event_id=model.event_id,
            event_creator_id=model.event_creator_id,
            event_title=model.event_title,
            event_latitude=model.event_latitude,
            event_longitude=model.event_longitude,
            starts_at=model.starts_at,
            ends_at=model.ends_at,
            event_status=model.event_status,
            event_privacy=model.event_privacy,
            created_at=model.created_at,
            updated_at=model.updated_at,
            event_description=model.event_description,
            location_name=model.location_name,
            max_participants=model.max_participants,
            cover_photo_url=model.cover_photo_url,
            deleted_at=model.deleted_at,
        )
