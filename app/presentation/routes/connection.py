from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BeforeValidator
from sqlalchemy.orm import Session

from app.domain.assemblers import ConnectionAssembler
from app.domain.entities import User
from app.domain.services import (
    DEFAULT_PENDING_CONNECTIONS_LIMIT,
    BlockService,
    CannotConnectToSelfError,
    ConnectionAlreadyExistsError,
    ConnectionService,
    InvalidPaginationError,
    NotificationDispatcher,
    ReceiverNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.connection import SqlAlchemyConnectionRepository
from app.presentation.dtos import (
    PendingConnectionsOutput,
    SendConnectionRequestInput,
    SendConnectionRequestOutput,
)
from app.presentation.mappers import ConnectionMapper
from app.presentation.routes.auth import get_current_user
from app.presentation.routes.events import get_notification_dispatcher
from app.presentation.routes.users import get_block_service

router = APIRouter(tags=["Connections"])


def _parse_limit(value: str | int) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error


def get_connection_service(
    db: Annotated[Session, Depends(get_db)],
    dispatcher: Annotated[NotificationDispatcher, Depends(get_notification_dispatcher)],
    block_service: Annotated[BlockService, Depends(get_block_service)],
) -> ConnectionService:
    return ConnectionService(
        repository=SqlAlchemyConnectionRepository(db, dispatcher),
        block_checker=block_service,
    )


@router.post(
    "/connections",
    response_model=SendConnectionRequestOutput,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar uma solicitação de conexão",
    description=(
        "Cria um vínculo PENDING entre o usuário autenticado (solicitante) e o "
        "destinatário informado. O destinatário recebe uma notificação. Conexão "
        "é só entre perfis pessoais."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "O destinatário informado é o próprio solicitante.",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Cannot send a connection request to yourself"
                    }
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": (
                "O destinatário não existe, ou há bloqueio entre os dois "
                "(mesmo erro nos dois casos, de propósito)."
            ),
            "content": {"application/json": {"example": {"detail": "User not found"}}},
        },
        status.HTTP_409_CONFLICT: {
            "description": "Já existe uma conexão ativa entre os dois usuários.",
            "content": {
                "application/json": {"example": {"detail": "Connection already exists"}}
            },
        },
    },
)
def send_connection_request(
    payload: SendConnectionRequestInput,
    current_user: Annotated[User, Depends(get_current_user)],
    connection_service: Annotated[ConnectionService, Depends(get_connection_service)],
) -> SendConnectionRequestOutput:
    receiver_id = ConnectionMapper.to_receiver_id(payload)
    try:
        connection = connection_service.send_request(current_user.user_id, receiver_id)
    except CannotConnectToSelfError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot send a connection request to yourself",
        ) from error
    except ReceiverNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from error
    except ConnectionAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connection already exists",
        ) from error
    return ConnectionAssembler.to_created_dto(connection)


@router.get(
    "/users/me/connections/pending",
    response_model=PendingConnectionsOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar as solicitações de conexão recebidas e não respondidas",
    description=(
        "Lista as solicitações de conexão PENDING em que o usuário autenticado "
        "é o destinatário, da mais recente para a mais antiga, para a central "
        "de notificações. `user` é sempre quem enviou a solicitação. "
        "Solicitações desfeitas, de contas excluídas ou entre usuários com "
        "bloqueio (em qualquer direção) não aparecem. Paginação por cursor "
        "opaco (`next_cursor`)."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`limit` ou `cursor` inválido.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid pagination parameters"}
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
            "description": "A conta associada ao token foi excluída.",
            "content": {
                "application/json": {"example": {"detail": "Account has been deleted"}}
            },
        },
    },
)
def list_pending_connection_requests(
    current_user: Annotated[User, Depends(get_current_user)],
    connection_service: Annotated[ConnectionService, Depends(get_connection_service)],
    limit: Annotated[
        int,
        BeforeValidator(_parse_limit),
        Query(description="Tamanho da página (1–100)."),
    ] = DEFAULT_PENDING_CONNECTIONS_LIMIT,
    cursor: Annotated[
        str | None, Query(description="Cursor opaco de paginação.")
    ] = None,
) -> PendingConnectionsOutput:
    assert current_user.user_id is not None
    try:
        page = connection_service.get_pending_requests(
            current_user.user_id, limit=limit, cursor=cursor
        )
    except InvalidPaginationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from error
    return ConnectionAssembler.to_pending_dto(page)
