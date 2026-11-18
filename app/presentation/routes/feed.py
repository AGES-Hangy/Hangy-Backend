from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import FeedAssembler
from app.domain.entities import User
from app.domain.services import (
    FeedService,
    InvalidFeedLocationError,
    InvalidFeedPaginationError,
    InvalidFeedRadiusError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.feed import SqlAlchemyFeedRepository
from app.presentation.dependencies.auth import get_current_user
from app.presentation.dtos import FeedOutput, FeedQuery

router = APIRouter(tags=["Feed"])


def get_feed_service(db: Annotated[Session, Depends(get_db)]) -> FeedService:
    return FeedService(repository=SqlAlchemyFeedRepository(db))


@router.get(
    "/feed",
    response_model=FeedOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar o feed da Home",
    description=(
        "Retorna os eventos futuros das tags de interesse do usuário "
        "autenticado, agrupados pela tag macro de cada interesse. Eventos "
        "criados pelo próprio usuário ou em que ele já está CONFIRMED não "
        "entram: eles ficam no perfil. Com `latitude` e `longitude` do "
        "aparelho, entram so os eventos a ate `radius_km` (padrao 100 km) "
        "dali, medidos pelo ponto aproximado do evento; sem elas, o feed nao "
        "filtra por distancia."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Paginacao, coordenadas ou raio invalidos.",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_pagination": {
                            "value": {"detail": "Invalid pagination parameters"}
                        },
                        "invalid_coordinates": {
                            "value": {"detail": "Invalid coordinates"}
                        },
                        "invalid_radius": {"value": {"detail": "Invalid radius"}},
                    }
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token de acesso ausente ou invalido."
        },
    },
)
def read_feed(
    query: Annotated[FeedQuery, Query()],
    current_user: Annotated[User, Depends(get_current_user)],
    feed_service: Annotated[FeedService, Depends(get_feed_service)],
) -> FeedOutput:
    try:
        feed = feed_service.get_feed(
            current_user.user_id,
            query.limit,
            latitude=query.latitude,
            longitude=query.longitude,
            radius_km=query.radius_km,
        )
    except InvalidFeedPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    except InvalidFeedLocationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid coordinates",
        ) from error
    except InvalidFeedRadiusError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid radius",
        ) from error
    return FeedAssembler.to_feed_dto(feed)
