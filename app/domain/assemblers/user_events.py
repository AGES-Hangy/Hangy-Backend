from app.domain.entities import UserEvent, UserEventsPage, UserEventsTabs
from app.presentation.dtos import (
    UserEventOutput,
    UserEventsOutput,
    UserEventsTabsOutput,
)


class UserEventsAssembler:
    @staticmethod
    def to_dto(page: UserEventsPage) -> UserEventsOutput:
        return UserEventsOutput(
            items=[UserEventsAssembler._to_item_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def to_tabs_dto(tabs: UserEventsTabs) -> UserEventsTabsOutput:
        return UserEventsTabsOutput(
            history=UserEventsAssembler._to_optional_dto(tabs.history),
            created=UserEventsAssembler._to_optional_dto(tabs.created),
            interests=UserEventsAssembler._to_optional_dto(tabs.interests),
            confirmed=UserEventsAssembler._to_optional_dto(tabs.confirmed),
        )

    @staticmethod
    def _to_optional_dto(page: UserEventsPage | None) -> UserEventsOutput | None:
        return UserEventsAssembler.to_dto(page) if page is not None else None

    @staticmethod
    def _to_item_dto(item: UserEvent) -> UserEventOutput:
        return UserEventOutput(
            event_id=item.event_id,
            title=item.title,
            event_date=item.starts_at,
            location_name=item.location_name,
            cover_photo_url=item.cover_photo_url,
            privacy=item.privacy,
            participation_status=item.participation_status,
        )
