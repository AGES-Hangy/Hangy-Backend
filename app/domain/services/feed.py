from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.domain.entities import Feed, FeedItem, FeedSection, Tag
from app.domain.enums import EventPrivacyEnum

DEFAULT_FEED_LIMIT = 10
MIN_FEED_LIMIT = 1
MAX_FEED_LIMIT = 50
# Guards the climb from a micro tag to its macro tag against a broken taxonomy.
MAX_TAG_DEPTH = 10


class FeedRepository(Protocol):
    def list_interest_tags(self, user_id: UUID) -> list[Tag]: ...

    def list_tags_by_ids(self, tag_ids: Collection[UUID]) -> list[Tag]: ...

    def list_events_for_tags(
        self,
        viewer_id: UUID,
        tag_ids: Collection[UUID],
        reference_time: datetime,
        limit: int,
    ) -> list[FeedItem]: ...


class InvalidFeedPaginationError(Exception):
    """Raised when the requested feed page size is outside the accepted range."""


class FeedService:
    def __init__(self, repository: FeedRepository) -> None:
        self.repository = repository

    def get_feed(self, user_id: UUID, limit: int = DEFAULT_FEED_LIMIT) -> Feed:
        if not MIN_FEED_LIMIT <= limit <= MAX_FEED_LIMIT:
            raise InvalidFeedPaginationError

        interest_tags = self.repository.list_interest_tags(user_id)
        if not interest_tags:
            # No interests means no sections: the app renders its empty state
            # instead of a generic feed (that variation still needs the PO).
            return Feed(sections=())

        reference_time = datetime.now(UTC)
        sections: list[FeedSection] = []
        for macro_tag, micro_tag_ids in self._group_by_macro_tag(interest_tags):
            # One extra row tells the section whether it has a next page.
            events = self.repository.list_events_for_tags(
                viewer_id=user_id,
                tag_ids=micro_tag_ids,
                reference_time=reference_time,
                limit=limit + 1,
            )
            if not events:
                continue
            sections.append(
                FeedSection(
                    tag=macro_tag,
                    items=tuple(
                        self._hide_restricted_details(event) for event in events[:limit]
                    ),
                    has_more=len(events) > limit,
                )
            )
        return Feed(sections=tuple(sections))

    @staticmethod
    def _hide_restricted_details(item: FeedItem) -> FeedItem:
        """Keep a PRIVATE event discoverable without giving it away.

        Anyone may find a PRIVATE event through its tags and ask to join, but
        when and where it happens is only revealed once the request is accepted.
        INVITE_ONLY events never reach the feed, so they need no masking here.
        """
        if item.privacy is not EventPrivacyEnum.PRIVATE:
            return item
        return replace(item, event_date=None, location_name=None)

    def _group_by_macro_tag(
        self, interest_tags: Sequence[Tag]
    ) -> list[tuple[Tag, list[UUID]]]:
        """Roll every interest tag up to its macro tag, keeping the micro ids.

        The user picks micro tags, but the Home groups by macro category, so the
        matching still happens on the micro ids collected under each macro tag.
        """
        known_tags = self._load_ancestors(interest_tags)

        macro_tags: dict[UUID, Tag] = {}
        micro_tag_ids: dict[UUID, list[UUID]] = {}
        for tag in interest_tags:
            if tag.tag_id is None:
                continue
            macro_tag = self._macro_tag_of(tag, known_tags)
            if macro_tag.tag_id is None:
                continue
            macro_tags.setdefault(macro_tag.tag_id, macro_tag)
            micro_tag_ids.setdefault(macro_tag.tag_id, []).append(tag.tag_id)

        return [
            (macro_tags[macro_tag_id], tag_ids)
            for macro_tag_id, tag_ids in sorted(
                micro_tag_ids.items(),
                key=lambda item: macro_tags[item[0]].tag_name,
            )
        ]

    def _load_ancestors(self, interest_tags: Sequence[Tag]) -> dict[UUID, Tag]:
        known_tags = {
            tag.tag_id: tag for tag in interest_tags if tag.tag_id is not None
        }
        pending = self._missing_parents(interest_tags, known_tags)
        for _ in range(MAX_TAG_DEPTH):
            if not pending:
                break
            parents = self.repository.list_tags_by_ids(pending)
            if not parents:
                break
            known_tags.update(
                {tag.tag_id: tag for tag in parents if tag.tag_id is not None}
            )
            pending = self._missing_parents(parents, known_tags)
        return known_tags

    @staticmethod
    def _missing_parents(tags: Sequence[Tag], known_tags: dict[UUID, Tag]) -> set[UUID]:
        return {
            tag.tag_parent_id
            for tag in tags
            if tag.tag_parent_id is not None and tag.tag_parent_id not in known_tags
        }

    @staticmethod
    def _macro_tag_of(tag: Tag, known_tags: dict[UUID, Tag]) -> Tag:
        current = tag
        visited: set[UUID] = set()
        while current.tag_parent_id is not None:
            parent = known_tags.get(current.tag_parent_id)
            # A parent that was not loaded, or a cycle in the taxonomy, stops
            # the climb and leaves the deepest tag we could reach as the macro.
            if parent is None or parent.tag_id is None or parent.tag_id in visited:
                break
            visited.add(parent.tag_id)
            current = parent
        return current
