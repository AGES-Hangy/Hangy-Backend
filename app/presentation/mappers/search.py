from datetime import date
from uuid import UUID

from app.domain.entities import SearchFilters, SearchQuery
from app.domain.services.search import (
    DEFAULT_SEARCH_PREVIEW_LIMIT,
    InvalidSearchDateFormatError,
    SearchTagNotFoundError,
)


class SearchMapper:
    @staticmethod
    def to_search_query(
        viewer_id: UUID,
        *,
        q: str | None = None,
        preview: int = DEFAULT_SEARCH_PREVIEW_LIMIT,
        tag_ids: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> SearchQuery:
        parsed_date_from = SearchMapper._parse_iso_date(date_from)
        parsed_date_to = SearchMapper._parse_iso_date(date_to)
        parsed_tag_ids = SearchMapper._parse_tag_ids(tag_ids)

        return SearchQuery(
            viewer_id=viewer_id,
            query=q,
            preview_limit=preview,
            filters=SearchFilters(
                tag_ids=parsed_tag_ids,
                date_from=parsed_date_from,
                date_to=parsed_date_to,
            ),
        )

    @staticmethod
    def _parse_iso_date(raw: str | None) -> date | None:
        if raw is None:
            return None
        cleaned = raw.strip()
        if not cleaned:
            return None
        if len(cleaned) != 10 or cleaned[4] != "-" or cleaned[7] != "-":
            raise InvalidSearchDateFormatError
        try:
            return date.fromisoformat(cleaned)
        except ValueError as error:
            raise InvalidSearchDateFormatError from error

    @staticmethod
    def _parse_tag_ids(raw: str | None) -> tuple[UUID, ...]:
        if raw is None:
            return ()
        cleaned = raw.strip()
        if not cleaned:
            return ()
        parsed: list[UUID] = []
        for part in cleaned.split(","):
            token = part.strip()
            if not token:
                raise SearchTagNotFoundError
            try:
                parsed.append(UUID(token))
            except ValueError as error:
                raise SearchTagNotFoundError from error
        return tuple(dict.fromkeys(parsed))


__all__ = ["SearchMapper"]
