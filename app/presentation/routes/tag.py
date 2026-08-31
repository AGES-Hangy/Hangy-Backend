from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.domain.assemblers import TagAssembler
from app.domain.services import TagService
from app.infrastructure.repository import get_db
from app.infrastructure.repository.tag_repository import SqlAlchemyTagRepository
from app.presentation.dtos import TagNodeOutput

router = APIRouter(prefix="/tags", tags=["Tags"])


def get_tag_service(db: Annotated[Session, Depends(get_db)]) -> TagService:
    return TagService(SqlAlchemyTagRepository(db))


@router.get(
    "/tree",
    response_model=list[TagNodeOutput],
    status_code=status.HTTP_200_OK,
    summary="Listar a árvore de categorias de tags",
    description=(
        "Retorna todas as tags macro com suas tags micro aninhadas, "
        "em uma única requisição."
    ),
)
def get_tag_tree(
    tag_service: Annotated[TagService, Depends(get_tag_service)],
) -> list[TagNodeOutput]:
    return TagAssembler.to_tree_dto(tag_service.get_tag_tree())
