from app.domain.entities import UserEvent, UserEventsPage
from app.presentation.dtos import UserEventOutput, UserEventsOutput


class UserEventsAssembler:
    @staticmethod
    def to_dto(page: UserEventsPage) -> UserEventsOutput:
        return UserEventsOutput(
            items=[UserEventsAssembler._to_item_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_item_dto(item: UserEvent) -> UserEventOutput:
        return UserEventOutput(
            event_id=item.event_id,
            title=item.title,
            event_date=item.starts_at,
            location_name=item.location_name,
            cover_photo_url=item.cover_photo_url,
            participation_status=item.participation_status,
        )