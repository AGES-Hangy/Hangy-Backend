from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.domain.assemblers import AuthAssembler
from app.domain.entities import User
from app.domain.services import AuthService, DuplicateEmailError
from app.presentation.dependencies.auth import (
    credentials_exception,
    get_auth_service,
    get_current_user,
)
from app.presentation.dtos import RegisterInput, TokenOutput, UserOutput
from app.presentation.mappers import UserMapper

router = APIRouter(tags=["Authentication"])


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
    except DuplicateEmailError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        ) from error
    return AuthAssembler.to_user_dto(user)


@router.post("/login", response_model=TokenOutput)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenOutput:
    # OAuth2 names the credential field "username"; Hangy authenticates by email.
    user = auth_service.authenticate(form_data.username, form_data.password)
    if user is None:
        raise credentials_exception
    return AuthAssembler.to_token_dto(auth_service.create_access_token(user))


@router.get("/users/me", response_model=UserOutput)
def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserOutput:
    return AuthAssembler.to_user_dto(current_user)
