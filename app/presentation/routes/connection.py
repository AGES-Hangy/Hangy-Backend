from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.domain.assemblers import ConnectionAssembler
from app.domain.entities import User
from app.domain.services import (
    CannotConnectToSelfError,
    ConnectionAlreadyExistsError,
    ConnectionService,
    NotificationDispatcher,
    ReceiverNotFoundError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.connection import SqlAlchemyConnectionRepository
from app.presentation.dtos import (
    SendConnectionRequestInput,
    SendConnectionRequestOutput,
)
from app.presentation.mappers import ConnectionMapper
from app.presentation.routes.auth import get_current_user
from app.presentation.routes.events import get_notification_dispatcher

router = APIRouter(tags=["Connections"])


def get_connection_service(
    db: Annotated[Session, Depends(get_db)],
    dispatcher: Annotated[NotificationDispatcher, Depends(get_notification_dispatcher)],
) -> ConnectionService:
    return ConnectionService(repository=SqlAlchemyConnectionRepository(db, dispatcher))


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
                "O destinatário não existe, ou bloqueou o solicitante "
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
