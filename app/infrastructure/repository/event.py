from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import Event, EventInviteLink, NewEvent
from app.domain.enums import (
    EventParticipantStatusEnum,
    EventStatusEnum,
    NotificationTypeEnum,
)
from app.infrastructure.repository.models import (
    EventCancelledNotificationModel,
    EventInviteLinkModel,
    EventModel,
    EventParticipantModel,
    NotificationModel,
    TagModel,
)


class SqlAlchemyEventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, event_id: UUID) -> Event | None:
        model = self.db.scalar(
            select(EventModel).where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
        )
        return self._to_entity(model) if model is not None else None

    def get_for_share(self, event_id: UUID) -> Event | None:
        model = self.db.scalar(
            select(EventModel).where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
                EventModel.event_status == EventStatusEnum.PUBLISHED,
            )
        )
        return self._to_entity(model) if model is not None else None

    def get_invite_link(self, event_id: UUID) -> EventInviteLink | None:
        model = self.db.scalar(
            select(EventInviteLinkModel)
            .where(EventInviteLinkModel.event_id == event_id)
            .order_by(EventInviteLinkModel.created_at.desc())
        )
        if model is None:
            return None
        return EventInviteLink(
            invite_id=model.invite_id,
            event_id=model.event_id,
            token=model.token,
            created_at=model.created_at,
            expires_at=model.expires_at,
        )

    def cancel(self, event_id: UUID) -> Event:
        model = self.db.scalar(
            select(EventModel).where(EventModel.event_id == event_id)
        )
        if model is None:
            raise ValueError("An event validated by the service must exist")

        model.event_status = EventStatusEnum.CANCELLED
        model.updated_at = datetime.now(UTC)
        participant_user_ids = self.db.scalars(
            select(EventParticipantModel.user_id).where(
                EventParticipantModel.event_id == event_id,
                EventParticipantModel.status.in_(
                    (
                        EventParticipantStatusEnum.CONFIRMED,
                        EventParticipantStatusEnum.PENDING,
                    )
                ),
            )
        ).all()
        for user_id in participant_user_ids:
            notification = NotificationModel(
                user_id=user_id,
                type=NotificationTypeEnum.EVENT_CANCELLED,
            )
            notification.event_cancelled_detail = EventCancelledNotificationModel(
                event_id=event_id
            )
            self.db.add(notification)
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    def find_existing_tag_ids(self, tag_ids: Collection[UUID]) -> set[UUID]:
        if not tag_ids:
            return set()
        return set(
            self.db.scalars(
                select(TagModel.tag_id).where(TagModel.tag_id.in_(tag_ids))
            ).all()
        )

    def add(self, event: NewEvent) -> Event:
        model = EventModel(
            event_creator_id=event.event_creator_id,
            event_title=event.event_title,
            event_description=event.event_description,
            event_latitude=event.event_latitude,
            event_longitude=event.event_longitude,
            location_name=event.location_name,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            max_participants=event.max_participants,
            event_status=EventStatusEnum.PUBLISHED,
            event_privacy=event.event_privacy,
            cover_photo_url=event.cover_photo_url,
        )
        if event.tag_ids:
            model.tags = list(
                self.db.scalars(
                    select(TagModel).where(TagModel.tag_id.in_(event.tag_ids))
                ).all()
            )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    def get(self, event_id: UUID) -> Event | None:
        model = self.db.scalar(
            select(EventModel).where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
        )
        return self._to_entity(model) if model is not None else None

    def update(self, event: Event, tag_ids: Collection[UUID] | None) -> Event:
        if event.event_id is None:
            raise ValueError("An event update requires an id")
        model = self.db.get(EventModel, event.event_id)
        if model is None:
            raise ValueError("Cannot update an event that does not exist")

        model.event_title = event.event_title
        model.event_description = event.event_description
        model.event_latitude = event.event_latitude
        model.event_longitude = event.event_longitude
        model.location_name = event.location_name
        model.starts_at = event.starts_at
        model.ends_at = event.ends_at
        model.cover_photo_url = event.cover_photo_url
        if tag_ids is not None:
            model.tags = list(
                self.db.scalars(
                    select(TagModel).where(TagModel.tag_id.in_(tag_ids))
                ).all()
            )

        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: EventModel) -> Event:
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
