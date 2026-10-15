from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BeforeValidator
from sqlalchemy.orm import Session

from app.domain.assemblers import ConnectionAssembler
from app.domain.entities import User
from app.domain.services import (
    BlockService,
    CannotConnectToSelfError,
    ConnectionAlreadyExistsError,
    ConnectionNotFoundError,
    ConnectionService,
    InvalidPaginationError,
    NotConnectionParticipantError,
    NotificationDispatcher,
    ReceiverNotFoundError,
)
from app.domain.services.connection import DEFAULT_CONNECTIONS_LIMIT
from app.infrastructure.repository import get_db
from app.infrastructure.repository.connection import SqlAlchemyConnectionRepository
from app.presentation.dtos import (
    ConnectionsOutput,
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
    ] = DEFAULT_CONNECTIONS_LIMIT,
    cursor: Annotated[
        str | None, Query(description="Cursor opaco de paginação.")
    ] = None,
) -> PendingConnectionsOutput:
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


@router.get(
    "/users/me/connections",
    response_model=ConnectionsOutput,
    status_code=status.HTTP_200_OK,
    summary="Listar conexões confirmadas do usuário autenticado",
    description=(
        "Lista as conexões CONFIRMED do usuário autenticado, excluindo "
        "usuários bloqueados (em qualquer direção), com busca opcional por "
        "nome (`q`) e paginação por cursor."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": "`limit` fora do intervalo 1-100 ou `cursor` malformado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Invalid pagination parameters"}
                }
            },
        },
    },
)
def list_my_connections(
    current_user: Annotated[User, Depends(get_current_user)],
    connection_service: Annotated[ConnectionService, Depends(get_connection_service)],
    q: Annotated[
        str | None, Query(max_length=100, description="Busca por nome")
    ] = None,
    limit: Annotated[
        int,
        BeforeValidator(_parse_limit),
        Query(description="Tamanho da página (1-100)"),
    ] = DEFAULT_CONNECTIONS_LIMIT,
    cursor: Annotated[
        str | None, Query(description="Cursor opaco de paginação")
    ] = None,
) -> ConnectionsOutput:
    try:
        page = connection_service.list_connections(
            current_user.user_id, search=q, limit=limit, cursor=cursor
        )
    except InvalidPaginationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters",
        ) from exc
    return ConnectionAssembler.to_connections_dto(page)


@router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desfazer uma conexão ou cancelar uma solicitação",
    description=(
        "Desfaz uma conexão existente ou cancela uma solicitação enviada; os "
        "dois lados (solicitante e destinatário) usam o mesmo endpoint. A "
        "remoção é lógica (`deleted_at`), então os usuários podem se conectar "
        "de novo depois. Nenhuma notificação é enviada."
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
            "description": "O usuário não é nem o solicitante nem o destinatário.",
            "content": {
                "application/json": {
                    "example": {"detail": "Not part of this connection"}
                }
            },
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Conexão inexistente ou já desfeita.",
            "content": {
                "application/json": {"example": {"detail": "Connection not found"}}
            },
        },
    },
)
def undo_connection(
    connection_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    connection_service: Annotated[ConnectionService, Depends(get_connection_service)],
) -> Response:
    assert current_user.user_id is not None
    try:
        connection_service.undo_connection(connection_id, current_user.user_id)
    except ConnectionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Connection not found",
        ) from error
    except NotConnectionParticipantError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not part of this connection",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
