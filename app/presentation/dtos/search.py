from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import EventPrivacyEnum, LocationPrecisionEnum
from app.domain.services.search import DEFAULT_SEARCH_PREVIEW_LIMIT


class SearchQueryParams(BaseModel):
    """Query parameters accepted by `GET /search`."""

    q: str | None = Field(
        default=None,
        description=(
            "Termo de busca (mínimo de 2 caracteres). Opcional quando há filtro."
        ),
    )
    preview: int = Field(
        default=DEFAULT_SEARCH_PREVIEW_LIMIT,
        description="Quantidade máxima de itens retornados no preview de cada bloco.",
    )
    tag_ids: str | None = Field(
        default=None,
        description="Lista de UUIDs de tags separados por vírgula (OR).",
    )
    date_from: str | None = Field(
        default=None,
        description=(
            "Data inicial do intervalo de `event_date` no formato ISO `YYYY-MM-DD`."
        ),
    )
    date_to: str | None = Field(
        default=None,
        description=(
            "Data final do intervalo de `event_date` no formato ISO `YYYY-MM-DD`."
        ),
    )


class SearchAppliedFiltersOutput(BaseModel):
    tag_ids: list[UUID]
    date_from: date | None
    date_to: date | None


class SearchEventItemOutput(BaseModel):
    event_id: UUID
    title: str
    event_date: datetime
    location_name: str | None
    location_precision: LocationPrecisionEnum
    privacy: EventPrivacyEnum
    is_preview: bool
    description: str | None
    participants_count: int | None
    cover_photo_url: str | None = None


class SearchBusinessItemOutput(BaseModel):
    user_id: UUID
    business_name: str | None
    name: str | None
    description: str | None = None
    address: str | None = None
    photo_url: str | None = None


class SearchUserItemOutput(BaseModel):
    user_id: UUID
    name: str | None
    description: str | None = None
    city: str | None = None
    state: str | None = None
    photo_url: str | None = None


class SearchEventsBlockOutput(BaseModel):
    items: list[SearchEventItemOutput]
    total: int
    has_more: bool


class SearchBusinessesBlockOutput(BaseModel):
    items: list[SearchBusinessItemOutput]
    total: int
    has_more: bool


class SearchUsersBlockOutput(BaseModel):
    items: list[SearchUserItemOutput]
    total: int
    has_more: bool


class SearchOutput(BaseModel):
    query: str | None
    applied_filters: SearchAppliedFiltersOutput
    events: SearchEventsBlockOutput
    businesses: SearchBusinessesBlockOutput
    users: SearchUsersBlockOutput


__all__ = [
    "SearchAppliedFiltersOutput",
    "SearchBusinessItemOutput",
    "SearchBusinessesBlockOutput",
    "SearchEventItemOutput",
    "SearchEventsBlockOutput",
    "SearchOutput",
    "SearchQueryParams",
    "SearchUserItemOutput",
    "SearchUsersBlockOutput",
]
