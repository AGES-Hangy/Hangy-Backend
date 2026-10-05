from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.domain.assemblers import TagAssembler
from app.domain.entities import User
from app.domain.services import (
    InvalidTagFilterError,
    OnlyMicroTagsSelectableError,
    TagNotFoundError,
    TagsService,
    UserNotFoundError,
    UserTagNotFoundError,
    UserTagsService,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.tag import SqlAlchemyTagRepository
from app.infrastructure.repository.user_tags import SqlAlchemyUserTagsRepository
from app.presentation.dtos import (
    ReplaceUserTagsInput,
    TagNodeOutput,
    TagOutput,
    UserTagsOutput,
)
from app.presentation.mappers import TagMapper, UserTagsMapper
from app.presentation.routes.auth import get_current_user

router = APIRouter(tags=["Tags"])


def get_tags_service(db: Annotated[Session, Depends(get_db)]) -> TagsService:
    return TagsService(repository=SqlAlchemyTagRepository(db))


def get_user_tags_service(db: Annotated[Session, Depends(get_db)]) -> UserTagsService:
    return UserTagsService(repository=SqlAlchemyUserTagsRepository(db))


@router.get(
    "/tags/tree",
    response_model=list[TagNodeOutput],
    status_code=status.HTTP_200_OK,
    summary="Listar a árvore de categorias de tags",
    description=(
        "Retorna todas as tags macro com suas tags micro aninhadas, "
        "em uma única requisição."
    ),
)
def get_tag_tree(
    tags_service: Annotated[TagsService, Depends(get_tags_service)],
) -> list[TagNodeOutput]:
    return TagAssembler.to_tree_dto(tags_service.get_tag_tree())


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
    tags_service: Annotated[TagsService, Depends(get_tags_service)],
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
        tags = tags_service.get_tags(
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


@router.get(
    "/users/me/tags",
    response_model=UserTagsOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar as tags de interesse do usuario autenticado",
    description=(
        "Retorna as tags de interesse atuais do usuario logado, cada uma com a "
        "sua tag macro em `parent`, para a tela de edicao abrir com elas "
        "pre-marcadas. A lista vem ordenada pelo nome da macro e depois pelo "
        "nome da tag. Um usuario sem tags recebe `tags` vazio."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, expirado ou invalido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
    },
)
def list_user_tags(
    current_user: Annotated[User, Depends(get_current_user)],
    user_tags_service: Annotated[UserTagsService, Depends(get_user_tags_service)],
) -> UserTagsOutput:
    tags = user_tags_service.get_tags(current_user.user_id)
    return TagAssembler.to_user_tags_dto(tags)


@router.put(
    "/users/me/tags",
    response_model=UserTagsOutput,
    status_code=status.HTTP_200_OK,
    summary="Substituir as tags de interesse do usuario autenticado",
    description=(
        "Define o conjunto final de tags de interesse do usuario logado, usado "
        "no passo de tags do cadastro e na edicao posterior. Apenas tags MICRO "
        "podem ser selecionadas; a macro e derivada pelo parent_tag_id. A "
        "operacao e idempotente: o conjunto enviado substitui integralmente o "
        "anterior."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "Uma das tags selecionadas e uma tag macro.",
            "content": {
                "application/json": {
                    "example": {"detail": "Only micro tags can be selected"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": (
                "Uma das tags selecionadas nao existe, ou o usuario autenticado "
                "nao existe mais."
            ),
            "content": {"application/json": {"example": {"detail": "Tag not found"}}},
        },
    },
)
def replace_user_tags(
    payload: ReplaceUserTagsInput,
    current_user: Annotated[User, Depends(get_current_user)],
    user_tags_service: Annotated[UserTagsService, Depends(get_user_tags_service)],
) -> UserTagsOutput:
    tag_ids = UserTagsMapper.to_tag_ids(payload)
    try:
        tags = user_tags_service.replace_tags(current_user.user_id, tag_ids)
    except UserTagNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        ) from error
    except OnlyMicroTagsSelectableError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only micro tags can be selected",
        ) from error
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from error
    return TagAssembler.to_user_tags_dto(tags)
