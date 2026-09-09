from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.entities import Event, EventInviteLink, NewEventInviteLink
from app.infrastructure.repository.models import EventInviteLinkModel, EventModel


class SqlAlchemyEventInviteLinkRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_event(self, event_id: UUID) -> Event | None:
        model = self.db.scalar(
            select(EventModel).where(
                EventModel.event_id == event_id,
                EventModel.deleted_at.is_(None),
            )
        )
        return self._event_to_entity(model) if model is not None else None

    def add_invite_link(self, invite_link: NewEventInviteLink) -> EventInviteLink:
        model = EventInviteLinkModel(
            event_id=invite_link.event_id,
            token=invite_link.token,
            created_by=invite_link.created_by,
            expires_at=invite_link.expires_at,
        )
        self.db.add(model)
        self.db.commit()
        self.db.refresh(model)
        return self._to_entity(model)

    @staticmethod
    def _event_to_entity(model: EventModel) -> Event:
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

    @staticmethod
    def _to_entity(model: EventInviteLinkModel) -> EventInviteLink:
        return EventInviteLink(
            invite_id=model.invite_id,
            event_id=model.event_id,
            token=model.token,
            created_by=model.created_by,
            created_at=model.created_at,
            expires_at=model.expires_at,
        )
