from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.assemblers import AuthAssembler
from app.domain.services import (
    AuthService,
    DuplicateUsernameError,
    InvalidAccessTokenError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.presentation.dtos import RegisterInput, TokenOutput, UserOutput
from app.presentation.mappers import UserMapper

router = APIRouter(tags=["Authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    return AuthService(
        repository=SqlAlchemyUserRepository(db),
        jwt_secret_key=settings.jwt_secret_key,
        jwt_algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
    )


credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post(
    "/register",
    response_model=UserOutput,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterInput,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserOutput:
    credentials = UserMapper.to_credentials(payload)
    try:
        user = auth_service.register(credentials)
    except DuplicateUsernameError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already registered",
        ) from error
    return AuthAssembler.to_user_dto(user)


@router.post("/login", response_model=TokenOutput)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenOutput:
    user = auth_service.authenticate(form_data.username, form_data.password)
    if user is None:
        raise credentials_exception
    return AuthAssembler.to_token_dto(auth_service.create_access_token(user))


@router.get("/users/me", response_model=UserOutput)
def read_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserOutput:
    try:
        user = auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error
    return AuthAssembler.to_user_dto(user)
