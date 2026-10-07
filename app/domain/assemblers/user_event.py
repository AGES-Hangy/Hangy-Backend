from app.domain.entities import UserEvent, UserEventsPage
from app.presentation.dtos import UserEventOutput, UserEventsOutput


class UserEventAssembler:
    @staticmethod
    def to_page_dto(page: UserEventsPage) -> UserEventsOutput:
        return UserEventsOutput(
            items=[UserEventAssembler._to_item_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def _to_item_dto(item: UserEvent) -> UserEventOutput:
        return UserEventOutput(
            event_id=item.event_id,
            title=item.title,
            event_date=item.event_date,
            location_name=item.location_name,
            cover_photo_url=item.cover_photo_url,
            privacy=item.privacy,
        )
