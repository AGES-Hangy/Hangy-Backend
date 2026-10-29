from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import AdminDashboardAssembler, TagAssembler
from app.domain.services import (
    AdminDashboardService,
    AdminTagsService,
    ParentTagNotCategoryError,
    ParentTagNotFoundError,
    TagNameAlreadyExistsError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.admin_dashboard import (
    SqlAlchemyAdminDashboardRepository,
)
from app.infrastructure.repository.tag import SqlAlchemyTagRepository
from app.presentation.dependencies.admin import require_admin
from app.presentation.dtos import (
    AdminDashboardOutput,
    AdminTagOutput,
    CreateAdminTagInput,
)
from app.presentation.mappers import AdminTagMapper

router = APIRouter(tags=["Admin"])

__all__ = ["router"]


def get_admin_dashboard_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminDashboardService:
    return AdminDashboardService(repository=SqlAlchemyAdminDashboardRepository(db))

def get_admin_tags_service(
    db: Annotated[Session, Depends(get_db)],
) -> AdminTagsService:
    return AdminTagsService(repository=SqlAlchemyTagRepository(db))


@router.get(
    "/admin/dashboard",
    response_model=AdminDashboardOutput,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_admin)],
    summary="Métricas do painel administrativo",
    description=(
        "Retorna as contagens de denúncias abertas (`PENDING`) e em análise "
        "(`REVIEWED`), de usuários ativos e de contas suspensas, mais as 5 "
        "denúncias `PENDING`/`REVIEWED` mais recentes. Exige Bearer token de "
        "um usuário com `role = ADMIN`."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, inválido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Usuário autenticado, mas `role != ADMIN`.",
            "content": {
                "application/json": {"example": {"detail": "Admin access required"}}
            },
        },
    },
)
def read_admin_dashboard(
    dashboard_service: Annotated[
        AdminDashboardService, Depends(get_admin_dashboard_service)
    ],
) -> AdminDashboardOutput:
    dashboard = dashboard_service.get_dashboard()
    return AdminDashboardAssembler.to_dto(dashboard)

@router.post(
    "/admin/tags",
    response_model=AdminTagOutput,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
    summary="Criar uma tag",
    description=(
        "Cria uma tag micro dentro de uma categoria existente (`parent_id` com "
        "o id da categoria) ou uma categoria nova, macro (`parent_id: null`). "
        "O nome e unico por nivel: entre as categorias, ou dentro da mesma "
        "categoria. Exige Bearer token de um usuario com `role = ADMIN`."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`parent_id` aponta para uma tag micro, nao uma macro.",
            "content": {
                "application/json": {
                    "example": {"detail": "Parent tag is not a category"}
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, inválido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Usuário autenticado, mas `role != ADMIN`.",
            "content": {
                "application/json": {"example": {"detail": "Admin access required"}}
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "O `parent_id` informado nao existe.",
            "content": {
                "application/json": {"example": {"detail": "Parent tag not found"}}
            },
        },
        status.HTTP_409_CONFLICT: {
            "description": "Ja existe uma tag com esse nome no mesmo nivel.",
            "content": {
                "application/json": {
                    "example": {"detail": "Tag name already exists at this level"}
                }
            },
        },
    },
)
def create_admin_tag(
    payload: CreateAdminTagInput,
    admin_tags_service: Annotated[AdminTagsService, Depends(get_admin_tags_service)],
) -> AdminTagOutput:
    tag = AdminTagMapper.to_entity(payload)
    try:
        created = admin_tags_service.create_tag(tag)
    except ParentTagNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent tag not found",
        ) from error
    except ParentTagNotCategoryError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parent tag is not a category",
        ) from error
    except TagNameAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tag name already exists at this level",
        ) from error
    return TagAssembler.to_admin_dto(created)
