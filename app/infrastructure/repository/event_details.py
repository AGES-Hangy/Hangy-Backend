from uuid import UUID

from sqlalchemy import Uuid, column, func, inspect, select, table
from sqlalchemy.orm import Session, joinedload

from app.domain.entities import (
    Event,
    EventDetailsData,
    EventDetailsOrganizer,
    EventDetailsParticipant,
    Tag,
)
from app.domain.enums import EventParticipantStatusEnum
from app.infrastructure.repository.models import (
    EventModel,
    EventParticipantModel,
)

USER_BLOCK_TABLE_NAME = "user_block"
user_block = table(
    USER_BLOCK_TABLE_NAME,
    column("blocker_id", Uuid),
    column("blocked_id", Uuid),
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
        row = (
            self.db.execute(
                select(
                    EventModel,
                    confirmed_count.label("confirmed_count"),
                    viewer_participation_status.label("viewer_participation_status"),
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

        model, participant_count, participation_status = row
        return self._to_entity(
            model=model,
            viewer_participation_status=participation_status,
            confirmed_participants_count=participant_count,
            organizer_blocked_viewer=self._organizer_blocked_viewer(
                organizer_id=model.event_creator_id,
                viewer_id=viewer_id,
            ),
        )

    def _organizer_blocked_viewer(self, organizer_id: UUID, viewer_id: UUID) -> bool:
        """Read task 087's table without owning its model or migration.

        The dependency is not yet present on ``develop``. A lightweight table
        clause keeps this task migration-free and starts enforcing the rule as
        soon as ``user_block`` lands.
        """
        bind = self.db.get_bind()
        if not inspect(bind).has_table(USER_BLOCK_TABLE_NAME):
            return False

        return (
            self.db.scalar(
                select(func.count())
                .select_from(user_block)
                .where(
                    user_block.c.blocker_id == organizer_id,
                    user_block.c.blocked_id == viewer_id,
                )
            )
            > 0
        )

    @staticmethod
    def _to_entity(
        model: EventModel,
        viewer_participation_status: EventParticipantStatusEnum | None,
        confirmed_participants_count: int,
        organizer_blocked_viewer: bool,
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
            event=SqlAlchemyEventDetailsRepository._to_event_entity(model),
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
