from collections.abc import Collection, Sequence
from datetime import UTC, date, datetime, time
from typing import Protocol
from uuid import UUID

from app.domain.entities import (
    SearchBusinessesPage,
    SearchBusinessesQuery,
    SearchBusinessItem,
    SearchEventCandidate,
    SearchEventItem,
    SearchEventsPage,
    SearchEventsQuery,
    SearchFilters,
    SearchQuery,
    SearchResult,
    SearchResultBlock,
    SearchUserItem,
    Tag,
)
from app.domain.enums import SearchResultType
from app.domain.services.event_visibility import resolve_event_visibility
from app.domain.services.pagination import (
    InvalidPaginationError,
    decode_cursor,
    decode_text_cursor,
    encode_cursor,
    encode_text_cursor,
)

DEFAULT_SEARCH_LIMIT = 20
MIN_SEARCH_QUERY_LENGTH = 2
MAX_SEARCH_QUERY_LENGTH = 120
DEFAULT_SEARCH_PREVIEW_LIMIT = 5
MIN_SEARCH_PREVIEW_LIMIT = 1
MAX_SEARCH_PREVIEW_LIMIT = 50
MAX_SEARCH_LIMIT = MAX_SEARCH_PREVIEW_LIMIT
MAX_TAG_DEPTH = 10


class SearchRepository(Protocol):
    def list_tags_by_ids(self, tag_ids: Collection[UUID]) -> list[Tag]: ...

    def list_child_tags(self, parent_ids: Collection[UUID]) -> list[Tag]: ...

    def search_events(
        self,
        viewer_id: UUID,
        *,
        query: str | None,
        tag_ids: Collection[UUID],
        date_from: datetime | None,
        date_to: datetime | None,
        reference_time: datetime,
        limit: int,
        offset: int = 0,
        after: tuple[datetime, UUID] | None = None,
    ) -> tuple[list[SearchEventCandidate], int]: ...

    def search_businesses(
        self,
        viewer_id: UUID,
        *,
        query: str,
        limit: int,
        offset: int = 0,
        after: tuple[str, UUID] | None = None,
    ) -> tuple[list[SearchBusinessItem], int]: ...

    def search_users(
        self,
        viewer_id: UUID,
        *,
        query: str,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[SearchUserItem], int]: ...


class SearchQueryTooShortError(Exception):
    """Raised when query has < 2 chars or both query and filters are missing."""


class InvalidSearchDateFormatError(Exception):
    """Raised when date_from or date_to is not a valid ISO YYYY-MM-DD date."""


class InvalidSearchDateRangeError(Exception):
    """Raised when date_from is after date_to."""


class SearchTagNotFoundError(Exception):
    """Raised when any requested tag_id does not exist."""


class InvalidSearchPreviewLimitError(Exception):
    """Raised when the requested preview limit is outside the accepted range."""


class SearchService:
    def __init__(self, repository: SearchRepository) -> None:
        self.repository = repository

    @staticmethod
    def _parse_limit(raw: str) -> int:
        try:
            if len(raw) > 10:
                raise InvalidPaginationError
            limit = int(raw)
        except ValueError as error:
            raise InvalidPaginationError from error
        if not 1 <= limit <= MAX_SEARCH_LIMIT:
            raise InvalidPaginationError
        return limit

    def search_businesses(
        self, criteria: SearchBusinessesQuery
    ) -> SearchBusinessesPage:
        limit = self._parse_limit(criteria.limit)
        after = None
        cursor = criteria.cursor
        if cursor is not None:
            if not cursor or len(cursor) > 256:
                raise InvalidPaginationError
            after = decode_text_cursor(cursor)
            if encode_text_cursor(*after) != cursor:
                raise InvalidPaginationError
        query = self._normalize_query(criteria.query, has_filters=False)
        if query is None:
            raise SearchQueryTooShortError
        items, total = self.repository.search_businesses(
            criteria.viewer_id, query=query, limit=limit + 1, after=after
        )
        page_items = tuple(items[:limit])
        next_cursor = None
        if len(items) > limit:
            last = page_items[-1]
            next_cursor = encode_text_cursor(last.name or "", last.user_id)
        return SearchBusinessesPage(
            items=page_items, next_cursor=next_cursor, total=total
        )

    def search_events(self, criteria: SearchEventsQuery) -> SearchEventsPage:
        limit = self._parse_limit(criteria.limit)
        after = None
        cursor = criteria.cursor
        if cursor is not None:
            if not cursor or len(cursor) > 256:
                raise InvalidPaginationError
            after = decode_cursor(cursor)
            if (
                after[0].tzinfo is None
                or after[0].utcoffset() is None
                or encode_cursor(*after) != cursor
            ):
                raise InvalidPaginationError
        filters = self._parse_events_filters(criteria)
        query = self._normalize_query(
            criteria.query,
            has_filters=bool(
                filters.tag_ids
                or filters.date_from is not None
                or filters.date_to is not None
            ),
        )
        if (
            filters.date_from is not None
            and filters.date_to is not None
            and filters.date_from > filters.date_to
        ):
            raise InvalidSearchDateRangeError
        expanded_tag_ids = self._validate_and_expand_tags(filters.tag_ids)
        candidates, total = self.repository.search_events(
            criteria.viewer_id,
            query=query,
            tag_ids=expanded_tag_ids,
            date_from=(
                datetime.combine(filters.date_from, time.min, tzinfo=UTC)
                if filters.date_from is not None
                else None
            ),
            date_to=(
                datetime.combine(filters.date_to, time.max, tzinfo=UTC)
                if filters.date_to is not None
                else None
            ),
            reference_time=datetime.now(UTC),
            limit=limit + 1,
            after=after,
        )
        items = tuple(
            self._to_event_item(candidate, criteria.viewer_id)
            for candidate in candidates[:limit]
        )
        next_cursor = None
        if len(candidates) > limit:
            last = items[-1]
            event_date = last.event_date
            if event_date.tzinfo is None:
                event_date = event_date.replace(tzinfo=UTC)
            next_cursor = encode_cursor(event_date, last.event_id)
        return SearchEventsPage(items=items, next_cursor=next_cursor, total=total)

    @staticmethod
    def _parse_events_date(raw: str | None) -> date | None:
        if raw is None or not raw.strip():
            return None
        cleaned = raw.strip()
        if len(cleaned) != 10 or cleaned[4] != "-" or cleaned[7] != "-":
            raise InvalidSearchDateFormatError
        try:
            return date.fromisoformat(cleaned)
        except ValueError as error:
            raise InvalidSearchDateFormatError from error

    @staticmethod
    def _parse_events_filters(criteria: SearchEventsQuery) -> SearchFilters:
        date_from = SearchService._parse_events_date(criteria.date_from)
        date_to = SearchService._parse_events_date(criteria.date_to)
        tag_ids: tuple[UUID, ...] = ()
        if criteria.tag_ids is not None and criteria.tag_ids.strip():
            try:
                tag_ids = tuple(
                    dict.fromkeys(
                        UUID(part.strip())
                        for part in criteria.tag_ids.strip().split(",")
                    )
                )
            except ValueError as error:
                raise SearchTagNotFoundError from error
        return SearchFilters(tag_ids=tag_ids, date_from=date_from, date_to=date_to)

    def search(self, criteria: SearchQuery) -> SearchResult:
        if (
            not (
                MIN_SEARCH_PREVIEW_LIMIT
                <= criteria.preview_limit
                <= MAX_SEARCH_PREVIEW_LIMIT
            )
            or criteria.offset < 0
        ):
            raise InvalidSearchPreviewLimitError

        filters = criteria.filters
        has_filters = bool(
            filters.tag_ids
            or filters.date_from is not None
            or filters.date_to is not None
        )

        normalized_query = self._normalize_query(
            criteria.query, has_filters=has_filters
        )

        if (
            filters.date_from is not None
            and filters.date_to is not None
            and filters.date_from > filters.date_to
        ):
            raise InvalidSearchDateRangeError

        expanded_tag_ids = self._validate_and_expand_tags(filters.tag_ids)
        reference_time = datetime.now(UTC)

        date_from_dt = (
            datetime.combine(filters.date_from, time.min, tzinfo=UTC)
            if filters.date_from is not None
            else None
        )
        date_to_dt = (
            datetime.combine(filters.date_to, time.max, tzinfo=UTC)
            if filters.date_to is not None
            else None
        )

        events_block = self._search_events_block(
            criteria=criteria,
            query=normalized_query,
            expanded_tag_ids=expanded_tag_ids,
            date_from=date_from_dt,
            date_to=date_to_dt,
            reference_time=reference_time,
        )
        businesses_block = self._search_businesses_block(
            criteria=criteria,
            query=normalized_query,
        )
        users_block = self._search_users_block(
            criteria=criteria,
            query=normalized_query,
        )

        return SearchResult(
            query=normalized_query,
            applied_filters=filters,
            events=events_block,
            businesses=businesses_block,
            users=users_block,
        )

    @staticmethod
    def _normalize_query(query: str | None, *, has_filters: bool) -> str | None:
        if query is None:
            if not has_filters:
                raise SearchQueryTooShortError
            return None

        cleaned = query.strip()
        if not cleaned:
            if not has_filters:
                raise SearchQueryTooShortError
            return None

        if len(cleaned) < MIN_SEARCH_QUERY_LENGTH:
            raise SearchQueryTooShortError

        return cleaned[:MAX_SEARCH_QUERY_LENGTH]

    def _validate_and_expand_tags(self, tag_ids: Sequence[UUID]) -> set[UUID]:
        if not tag_ids:
            return set()

        unique_ids = set(tag_ids)
        existing_tags = self.repository.list_tags_by_ids(unique_ids)
        if len(existing_tags) != len(unique_ids):
            raise SearchTagNotFoundError

        expanded: set[UUID] = set(unique_ids)
        frontier: set[UUID] = set(unique_ids)
        for _ in range(MAX_TAG_DEPTH):
            if not frontier:
                break
            children = self.repository.list_child_tags(frontier)
            new_child_ids = {
                child.tag_id
                for child in children
                if child.tag_id is not None and child.tag_id not in expanded
            }
            if not new_child_ids:
                break
            expanded.update(new_child_ids)
            frontier = new_child_ids

        return expanded

    def _search_events_block(
        self,
        *,
        criteria: SearchQuery,
        query: str | None,
        expanded_tag_ids: set[UUID],
        date_from: datetime | None,
        date_to: datetime | None,
        reference_time: datetime,
    ) -> SearchResultBlock[SearchEventItem]:
        if criteria.result_type not in (None, SearchResultType.EVENT):
            return SearchResultBlock(items=(), total=0, has_more=False)

        candidates, total = self.repository.search_events(
            criteria.viewer_id,
            query=query,
            tag_ids=expanded_tag_ids,
            date_from=date_from,
            date_to=date_to,
            reference_time=reference_time,
            limit=criteria.preview_limit,
            offset=criteria.offset,
        )
        items = tuple(
            self._to_event_item(candidate, criteria.viewer_id)
            for candidate in candidates
        )
        return SearchResultBlock(
            items=items,
            total=total,
            has_more=(criteria.offset + len(items)) < total,
        )

    def _search_businesses_block(
        self,
        *,
        criteria: SearchQuery,
        query: str | None,
    ) -> SearchResultBlock[SearchBusinessItem]:
        if query is None or criteria.result_type not in (
            None,
            SearchResultType.BUSINESS,
        ):
            return SearchResultBlock(items=(), total=0, has_more=False)

        items, total = self.repository.search_businesses(
            criteria.viewer_id,
            query=query,
            limit=criteria.preview_limit,
            offset=criteria.offset,
        )
        return SearchResultBlock(
            items=tuple(items),
            total=total,
            has_more=(criteria.offset + len(items)) < total,
        )

    def _search_users_block(
        self,
        *,
        criteria: SearchQuery,
        query: str | None,
    ) -> SearchResultBlock[SearchUserItem]:
        if query is None or criteria.result_type not in (None, SearchResultType.USER):
            return SearchResultBlock(items=(), total=0, has_more=False)

        items, total = self.repository.search_users(
            criteria.viewer_id,
            query=query,
            limit=criteria.preview_limit,
            offset=criteria.offset,
        )
        return SearchResultBlock(
            items=tuple(items),
            total=total,
            has_more=(criteria.offset + len(items)) < total,
        )

    @staticmethod
    def _to_event_item(
        candidate: SearchEventCandidate, viewer_id: UUID
    ) -> SearchEventItem:
        event = candidate.event
        if event.event_id is None:
            raise ValueError("A persisted event must have an id")
        visibility = resolve_event_visibility(
            event,
            viewer_id=viewer_id,
            participation_status=candidate.viewer_participation_status,
            participants_count=candidate.participants_count,
        )
        return SearchEventItem(
            event_id=event.event_id,
            title=event.event_title,
            event_date=event.starts_at,
            location=visibility.location,
            privacy=event.event_privacy,
            is_preview=visibility.is_preview,
            description=visibility.description,
            participants_count=visibility.participants_count,
            cover_photo_url=event.cover_photo_url,
        )


__all__ = [
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_SEARCH_PREVIEW_LIMIT",
    "InvalidSearchDateFormatError",
    "InvalidSearchDateRangeError",
    "InvalidSearchPreviewLimitError",
    "MAX_SEARCH_LIMIT",
    "MAX_SEARCH_PREVIEW_LIMIT",
    "MAX_SEARCH_QUERY_LENGTH",
    "MIN_SEARCH_PREVIEW_LIMIT",
    "MIN_SEARCH_QUERY_LENGTH",
    "SearchQueryTooShortError",
    "SearchRepository",
    "SearchService",
    "SearchTagNotFoundError",
]
