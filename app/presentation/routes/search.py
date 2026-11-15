from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import SearchAssembler
from app.domain.entities import User
from app.domain.services import (
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_SEARCH_PREVIEW_LIMIT,
    MAX_SEARCH_QUERY_LENGTH,
    InvalidPaginationError,
    InvalidSearchDateFormatError,
    InvalidSearchDateRangeError,
    InvalidSearchPreviewLimitError,
    SearchQueryTooShortError,
    SearchService,
    SearchTagNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.search import SqlAlchemySearchRepository
from app.presentation.dependencies.auth import credentials_exception, get_current_user
from app.presentation.dtos import (
    SearchBusinessesPageOutput,
    SearchEventsPageOutput,
    SearchOutput,
    SearchUsersPageOutput,
)
from app.presentation.mappers import SearchMapper

router = APIRouter(tags=["Search"])

BAD_REQUEST_EXAMPLES = {
    "query_too_short": {
        "summary": "Termo com menos de 2 caracteres ou sem termo e sem filtro",
        "value": {"detail": "Query is too short"},
    },
    "invalid_date_range": {
        "summary": "Intervalo de datas invertido",
        "value": {"detail": "date_from must be before date_to"},
    },
    "invalid_date_format": {
        "summary": "Data fora do formato ISO YYYY-MM-DD",
        "value": {"detail": "Invalid date format"},
    },
}


def get_search_service(db: Annotated[Session, Depends(get_db)]) -> SearchService:
    return SearchService(repository=SqlAlchemySearchRepository(db))


@router.get(
    "/search",
    response_model=SearchOutput,
    status_code=status.HTTP_200_OK,
    summary="Buscar eventos, estabelecimentos e pessoas",
    description=(
        "Retorna resultados categorizados em três blocos (`events`, "
        "`businesses`, `users`), com preview configurável por bloco. "
        "Os filtros `tag_ids`, `date_from` e `date_to` recortam apenas o bloco "
        "de eventos e podem ser usados sem termo (`q`). Eventos `PRIVATE` em "
        "que o solicitante não participa voltam em modo preview com local "
        "aproximado (`location_precision: APPROXIMATE`); eventos `INVITE_ONLY` "
        "só aparecem para quem foi convidado."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": (
                "Termo curto demais, formato de data inválido ou intervalo invertido."
            ),
            "content": {"application/json": {"examples": BAD_REQUEST_EXAMPLES}},
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Algum `tag_id` informado não existe.",
            "content": {"application/json": {"example": {"detail": "Tag not found"}}},
        },
    },
)
def search(
    current_user: Annotated[User, Depends(get_current_user)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    q: Annotated[
        str | None,
        Query(description="Termo de busca, mínimo de 2 caracteres."),
    ] = None,
    preview: Annotated[
        int,
        Query(description="Quantidade máxima de itens retornados em cada bloco."),
    ] = DEFAULT_SEARCH_PREVIEW_LIMIT,
    tag_ids: Annotated[
        str | None,
        Query(description="Lista de UUIDs de tags separados por vírgula (OR)."),
    ] = None,
    date_from: Annotated[
        str | None,
        Query(description="Início do intervalo de `event_date` (`YYYY-MM-DD`)."),
    ] = None,
    date_to: Annotated[
        str | None,
        Query(description="Fim do intervalo de `event_date` (`YYYY-MM-DD`)."),
    ] = None,
) -> SearchOutput:
    if current_user.user_id is None:
        raise credentials_exception

    try:
        criteria = SearchMapper.to_search_query(
            current_user.user_id,
            q=q,
            preview=preview,
            tag_ids=tag_ids,
            date_from=date_from,
            date_to=date_to,
        )
        result = search_service.search(criteria)
    except SearchQueryTooShortError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query is too short",
        ) from error
    except InvalidSearchDateFormatError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format",
        ) from error
    except InvalidSearchDateRangeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_from must be before date_to",
        ) from error
    except InvalidSearchPreviewLimitError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    except SearchTagNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        ) from error

    return SearchAssembler.to_dto(result)


@router.get(
    "/search/events",
    response_model=SearchEventsPageOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar todos os eventos da busca",
    description=(
        "Mantém o termo, as tags e as datas do bloco de eventos da busca. "
        "Ordena por data crescente e ID, com paginação por cursor (padrão 20, "
        "máximo 50). Eventos privados em preview exibem apenas bairro/cidade "
        "e location_precision APPROXIMATE."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Paginação, termo ou datas inválidos.",
            "content": {
                "application/json": {
                    "examples": {
                        **BAD_REQUEST_EXAMPLES,
                        "invalid_pagination": {
                            "value": {"detail": "Invalid pagination parameters"}
                        },
                    }
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Algum tag_id informado não existe.",
            "content": {"application/json": {"example": {"detail": "Tag not found"}}},
        },
    },
)
def search_events(
    current_user: Annotated[User, Depends(get_current_user)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    q: Annotated[str | None, Query(max_length=MAX_SEARCH_QUERY_LENGTH)] = None,
    tag_ids: Annotated[str | None, Query(max_length=4096)] = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: Annotated[str, Query(description="Tamanho da página: 1 a 50.")] = str(
        DEFAULT_SEARCH_LIMIT
    ),
    cursor: str | None = None,
) -> SearchEventsPageOutput:
    if current_user.user_id is None:
        raise credentials_exception
    try:
        criteria = SearchMapper.to_events_query(
            current_user.user_id,
            q=q,
            limit=limit,
            tag_ids=tag_ids,
            date_from=date_from,
            date_to=date_to,
            cursor=cursor,
        )
        page = search_service.search_events(criteria)
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    except SearchQueryTooShortError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Query is too short"
        ) from error
    except InvalidSearchDateFormatError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid date format"
        ) from error
    except InvalidSearchDateRangeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_from must be before date_to",
        ) from error
    except SearchTagNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found"
        ) from error
    return SearchAssembler.to_events_page_dto(page)


@router.get(
    "/search/businesses",
    response_model=SearchBusinessesPageOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar todos os estabelecimentos da busca",
    description=(
        "Mantém o termo da busca (`q`, mínimo de 2 caracteres). Ordena por nome "
        "e ID, com paginação por cursor (padrão 20, máximo 50). Estabelecimentos "
        "bloqueados (nos dois sentidos) não aparecem."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`limit` ou `cursor` inválido, ou termo curto demais.",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_pagination": {
                            "value": {"detail": "Invalid pagination parameters"}
                        },
                        "query_too_short": {"value": {"detail": "Query is too short"}},
                    }
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
    },
)
def search_businesses(
    current_user: Annotated[User, Depends(get_current_user)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    q: Annotated[str | None, Query(max_length=MAX_SEARCH_QUERY_LENGTH)] = None,
    limit: Annotated[str, Query(description="Tamanho da página: 1 a 50.")] = str(
        DEFAULT_SEARCH_LIMIT
    ),
    cursor: str | None = None,
) -> SearchBusinessesPageOutput:
    if current_user.user_id is None:
        raise credentials_exception
    try:
        criteria = SearchMapper.to_businesses_query(
            current_user.user_id, q=q, limit=limit, cursor=cursor
        )
        page = search_service.search_businesses(criteria)
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    except SearchQueryTooShortError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Query is too short"
        ) from error
    return SearchAssembler.to_businesses_page_dto(page)


@router.get(
    "/search/users",
    response_model=SearchUsersPageOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar todas as pessoas da busca",
    description=(
        "Mantém o termo do bloco de pessoas da busca. "
        "Ordena por nome crescente e ID, com paginação por cursor (padrão 20, "
        "máximo 50). Nunca devolve perfis em que haja bloqueio bilateral com o "
        "solicitante."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Paginação ou termo inválidos.",
            "content": {
                "application/json": {
                    "examples": {
                        "query_too_short": BAD_REQUEST_EXAMPLES["query_too_short"],
                        "invalid_pagination": {
                            "summary": "Limite fora do intervalo ou cursor malformado",
                            "value": {"detail": "Invalid pagination parameters"},
                        },
                    }
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
    },
)
def search_users(
    current_user: Annotated[User, Depends(get_current_user)],
    search_service: Annotated[SearchService, Depends(get_search_service)],
    q: Annotated[
        str | None,
        Query(
            max_length=MAX_SEARCH_QUERY_LENGTH,
            description="Termo de busca, mínimo de 2 caracteres.",
        ),
    ] = None,
    limit: Annotated[str, Query(description="Tamanho da página: 1 a 50.")] = str(
        DEFAULT_SEARCH_LIMIT
    ),
    cursor: Annotated[
        str | None,
        Query(description="Cursor opaco de paginação retornado na página anterior."),
    ] = None,
) -> SearchUsersPageOutput:
    if current_user.user_id is None:
        raise credentials_exception
    try:
        criteria = SearchMapper.to_users_query(
            current_user.user_id,
            q=q,
            limit=limit,
            cursor=cursor,
        )
        page = search_service.search_users(criteria)
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    except SearchQueryTooShortError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Query is too short"
        ) from error
    return SearchAssembler.to_users_page_dto(page)


__all__ = [
    "get_search_service",
    "router",
    "search",
    "search_businesses",
    "search_events",
    "search_users",
]
