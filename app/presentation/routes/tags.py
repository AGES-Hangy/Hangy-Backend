from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import TagAssembler
from app.domain.services import GetTags, InvalidTagFilterError, TagNotFoundError
from app.infrastructure.repository import get_db
from app.infrastructure.repository.tag import SqlAlchemyTagRepository
from app.presentation.dtos import TagOutput
from app.presentation.mappers import TagMapper

router = APIRouter(tags=["Tags"])


def get_tags_service(db: Annotated[Session, Depends(get_db)]) -> GetTags:
    return GetTags(repository=SqlAlchemyTagRepository(db))


@router.get(
    "/tags",
    response_model=list[TagOutput],
    status_code=status.HTTP_200_OK,
    summary="Listar as tags do sistema",
    description=(
        "Sem filtro devolve todas as tags. `type=MACRO` devolve apenas as "
        "categorias e `parent_id` devolve as tags micro de uma macro. "
        "Os dois filtros sao mutuamente exclusivos."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Filtros invalidos ou combinados entre si.",
            "content": {
                "application/json": {"example": {"detail": "Invalid tag filter"}}
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O `parent_id` informado nao e uma tag macro existente.",
            "content": {"application/json": {"example": {"detail": "Tag not found"}}},
        },
    },
)
def list_tags(
    get_tags: Annotated[GetTags, Depends(get_tags_service)],
    tag_type: Annotated[
        str | None,
        Query(alias="type", description="MACRO ou MICRO."),
    ] = None,
    parent_id: Annotated[
        str | None,
        Query(description="Id da tag macro cujas tags micro serao listadas."),
    ] = None,
) -> list[TagOutput]:
    try:
        tags = get_tags.execute(
            tag_type=TagMapper.to_tag_type(tag_type),
            parent_id=TagMapper.to_parent_id(parent_id),
        )
    except InvalidTagFilterError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tag filter",
        ) from error
    except TagNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        ) from error
    return TagAssembler.to_dtos(tags)
