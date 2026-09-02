from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import Event, NewEvent
from app.domain.enums import EventStatusEnum
from app.infrastructure.repository.models import EventModel, TagModel


class SqlAlchemyEventRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

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
