from app.domain.entities import (
    SearchBusinessesPage,
    SearchBusinessItem,
    SearchEventItem,
    SearchEventsPage,
    SearchResult,
    SearchUserItem,
    SearchUsersPage,
)
from app.presentation.dtos import (
    SearchAppliedFiltersOutput,
    SearchBusinessesBlockOutput,
    SearchBusinessesPageOutput,
    SearchBusinessItemOutput,
    SearchBusinessPageItemOutput,
    SearchEventItemOutput,
    SearchEventsBlockOutput,
    SearchEventsPageOutput,
    SearchOutput,
    SearchUserItemOutput,
    SearchUsersBlockOutput,
    SearchUsersPageOutput,
)


class SearchAssembler:
    @staticmethod
    def to_events_page_dto(page: SearchEventsPage) -> SearchEventsPageOutput:
        return SearchEventsPageOutput(
            items=[SearchAssembler._to_event_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
            total=page.total,
        )

    @staticmethod
    def to_businesses_page_dto(
        page: SearchBusinessesPage,
    ) -> SearchBusinessesPageOutput:
        return SearchBusinessesPageOutput(
            items=[
                SearchBusinessPageItemOutput(
                    user_id=item.user_id,
                    business_name=item.business_name,
                    photo_url=item.photo_url,
                    city=item.city,
                    is_following=item.is_following,
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
            total=page.total,
        )

    @staticmethod
    def to_users_page_dto(page: SearchUsersPage) -> SearchUsersPageOutput:
        return SearchUsersPageOutput(
            items=[SearchAssembler._to_user_dto(item) for item in page.items],
            next_cursor=page.next_cursor,
            total=page.total,
        )

    @staticmethod
    def to_dto(result: SearchResult) -> SearchOutput:
        return SearchOutput(
            query=result.query,
            applied_filters=SearchAppliedFiltersOutput(
                tag_ids=list(result.applied_filters.tag_ids),
                date_from=result.applied_filters.date_from,
                date_to=result.applied_filters.date_to,
            ),
            events=SearchEventsBlockOutput(
                items=[
                    SearchAssembler._to_event_dto(item) for item in result.events.items
                ],
                total=result.events.total,
                has_more=result.events.has_more,
            ),
            businesses=SearchBusinessesBlockOutput(
                items=[
                    SearchAssembler._to_business_dto(item)
                    for item in result.businesses.items
                ],
                total=result.businesses.total,
                has_more=result.businesses.has_more,
            ),
            users=SearchUsersBlockOutput(
                items=[
                    SearchAssembler._to_user_dto(item) for item in result.users.items
                ],
                total=result.users.total,
                has_more=result.users.has_more,
            ),
        )

    @staticmethod
    def _to_event_dto(item: SearchEventItem) -> SearchEventItemOutput:
        return SearchEventItemOutput(
            event_id=item.event_id,
            title=item.title,
            event_date=item.event_date,
            location_name=item.location.label,
            location_precision=item.location.precision,
            privacy=item.privacy,
            is_preview=item.is_preview,
            description=item.description,
            participants_count=item.participants_count,
            cover_photo_url=item.cover_photo_url,
        )

    @staticmethod
    def _to_business_dto(item: SearchBusinessItem) -> SearchBusinessItemOutput:
        return SearchBusinessItemOutput(
            user_id=item.user_id,
            business_name=item.business_name,
            name=item.name,
            description=item.description,
            address=item.address,
            photo_url=item.photo_url,
        )

    @staticmethod
    def _to_user_dto(item: SearchUserItem) -> SearchUserItemOutput:
        return SearchUserItemOutput(
            user_id=item.user_id,
            name=item.name,
            description=item.description,
            city=item.city,
            state=item.state,
            photo_url=item.photo_url,
            connection_status=item.connection_status,
        )


__all__ = ["SearchAssembler"]
