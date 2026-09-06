from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import FeedAssembler
from app.domain.entities import User
from app.domain.services import FeedService, InvalidFeedPaginationError
from app.infrastructure.repository import get_db
from app.infrastructure.repository.feed import SqlAlchemyFeedRepository
from app.presentation.dtos import FeedOutput, FeedQuery
from app.presentation.routes.auth import get_current_user

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
        "autenticado, agrupados pela tag macro de cada interesse."
    ),
)
def read_feed(
    query: Annotated[FeedQuery, Query()],
    current_user: Annotated[User, Depends(get_current_user)],
    feed_service: Annotated[FeedService, Depends(get_feed_service)],
) -> FeedOutput:
    try:
        feed = feed_service.get_feed(current_user.user_id, query.limit)
    except InvalidFeedPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    return FeedAssembler.to_feed_dto(feed)
