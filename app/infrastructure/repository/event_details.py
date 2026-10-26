from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, joinedload

from app.domain.entities import (
    EventDetailsData,
    EventDetailsOrganizer,
    EventDetailsParticipant,
    Tag,
)
from app.domain.enums import EventParticipantStatusEnum
from app.infrastructure.repository.event import SqlAlchemyEventRepository
from app.infrastructure.repository.models import (
    EventFavoriteModel,
    EventModel,
    EventParticipantModel,
)


class SqlAlchemyEventDetailsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_details(self, event_id: UUID, viewer_id: UUID) -> EventDetailsData | None:
        confirmed_count = (
            select(func.count(EventParticipantModel.participant_id))
            .where(
                EventParticipantModel.event_id == EventModel.event_id,
                EventParticipantModel.status == EventParticipantStatusEnum.CONFIRMED,
            )
            .correlate(EventModel)
            .scalar_subquery()
        )
        viewer_participation_status = (
            select(EventParticipantModel.status)
            .where(
                EventParticipantModel.event_id == EventModel.event_id,
                EventParticipantModel.user_id == viewer_id,
            )
            .correlate(EventModel)
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
        row = (
            self.db.execute(
                select(
                    EventModel,
                    confirmed_count.label("confirmed_count"),
                    viewer_participation_status.label("viewer_participation_status"),
                    viewer_favorited.label("viewer_favorited"),
                )
                .where(
                    EventModel.event_id == event_id,
                    EventModel.deleted_at.is_(None),
                )
                .options(
                    joinedload(EventModel.creator),
                    joinedload(EventModel.tags),
                    joinedload(EventModel.participants).joinedload(
                        EventParticipantModel.user
                    ),
                )
            )
            .unique()
            .one_or_none()
        )
        if row is None:
            return None

        model, participant_count, participation_status, favorited = row
        return self._to_entity(
            model=model,
            viewer_participation_status=participation_status,
            confirmed_participants_count=participant_count,
            organizer_blocked_viewer=self.organizer_blocked_viewer(
                organizer_id=model.event_creator_id,
                viewer_id=viewer_id,
            ),
            viewer_favorited=favorited,
        )

    def organizer_blocked_viewer(self, organizer_id: UUID, viewer_id: UUID) -> bool:
        from app.infrastructure.repository.block_access import block_exists_between

        return bool(
            self.db.scalar(select(block_exists_between(organizer_id, viewer_id)))
        )

    @staticmethod
    def _to_entity(
        model: EventModel,
        viewer_participation_status: EventParticipantStatusEnum | None,
        confirmed_participants_count: int,
        organizer_blocked_viewer: bool,
        viewer_favorited: bool,
    ) -> EventDetailsData:
        participants = tuple(
            sorted(
                (
                    SqlAlchemyEventDetailsRepository._to_participant_entity(participant)
                    for participant in model.participants
                    if participant.status is EventParticipantStatusEnum.CONFIRMED
                ),
                key=lambda participant: (
                    participant.requested_at,
                    str(participant.participant_id),
                ),
            )
        )
        return EventDetailsData(
            event=SqlAlchemyEventRepository.to_entity(model),
            tags=tuple(
                Tag(
                    tag_id=tag.tag_id,
                    tag_name=tag.tag_name,
                    tag_parent_id=tag.tag_parent_id,
                )
                for tag in sorted(
                    model.tags,
                    key=lambda tag: (
                        tag.tag_parent_id is not None,
                        tag.tag_name,
                        tag.tag_id,
                    ),
                )
            ),
            organizer=EventDetailsOrganizer(
                user_id=model.creator.user_id,
                name=model.creator.name,
                user_type=model.creator.user_type,
            ),
            viewer_participation_status=viewer_participation_status,
            confirmed_participants_count=confirmed_participants_count,
            confirmed_participants=participants,
            organizer_blocked_viewer=organizer_blocked_viewer,
            viewer_favorited=viewer_favorited,
        )

    @staticmethod
    def _to_participant_entity(
        model: EventParticipantModel,
    ) -> EventDetailsParticipant:
        return EventDetailsParticipant(
            participant_id=model.participant_id,
            user_id=model.user.user_id,
            name=model.user.name,
            user_type=model.user.user_type,
            avatar_url=model.user.profile_photo_url,
            status=model.status,
            requested_at=model.joined_at,
        )
