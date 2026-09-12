from uuid import UUID

from sqlalchemy.orm import Session

from app.domain.entities import Event, EventInviteLink, NewEventInviteLink
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import EventInviteLinkModel


class SqlAlchemyEventInviteLinkRepository:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.event_repository = SqlAlchemyEventRepository(db)

    def get_by_id(self, event_id: UUID) -> Event | None:
        return self.event_repository.get_by_id(event_id)

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
    def _to_entity(model: EventInviteLinkModel) -> EventInviteLink:
        return EventInviteLink(
            invite_id=model.invite_id,
            event_id=model.event_id,
            token=model.token,
            created_by=model.created_by,
            created_at=model.created_at,
            expires_at=model.expires_at,
        )
