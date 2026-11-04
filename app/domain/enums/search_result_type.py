from enum import StrEnum


class SearchResultType(StrEnum):
    EVENT = "EVENT"
    BUSINESS = "BUSINESS"
    USER = "USER"


SearchResultTypeEnum = SearchResultType

__all__ = ["SearchResultType", "SearchResultTypeEnum"]
