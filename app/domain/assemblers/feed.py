from app.domain.entities import Feed, FeedItem, FeedSection
from app.presentation.dtos import (
    FeedItemOutput,
    FeedOutput,
    FeedSectionOutput,
    FeedTagOutput,
)


class FeedAssembler:
    @staticmethod
    def to_feed_dto(feed: Feed) -> FeedOutput:
        return FeedOutput(
            sections=[
                FeedAssembler._to_section_dto(section) for section in feed.sections
            ]
        )

    @staticmethod
    def _to_section_dto(section: FeedSection) -> FeedSectionOutput:
        if section.tag.tag_id is None:
            raise ValueError("A persisted tag must have an id")
        return FeedSectionOutput(
            tag=FeedTagOutput(id=section.tag.tag_id, name=section.tag.tag_name),
            items=[FeedAssembler._to_item_dto(item) for item in section.items],
            has_more=section.has_more,
        )

    @staticmethod
    def _to_item_dto(item: FeedItem) -> FeedItemOutput:
        return FeedItemOutput(
            event_id=item.event_id,
            title=item.title,
            event_date=item.event_date,
            location_name=item.location_name,
            cover_photo_url=item.cover_photo_url,
            privacy=item.privacy,
            participants_count=item.participants_count,
        )
