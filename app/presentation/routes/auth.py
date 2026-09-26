from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.assemblers import AuthAssembler, DeviceAssembler
from app.domain.entities import User
from app.domain.services import (
    AccountDeletedError,
    AuthService,
    DeviceService,
    DuplicateCnpjError,
    DuplicateCpfError,
    DuplicateEmailError,
    InvalidAccessTokenError,
    InvalidCnpjError,
    InvalidCoordinatesError,
    InvalidCpfError,
    InvalidCredentialsError,
    InvalidDeviceTokenError,
    MinimumAgeError,
    RegisterBusinessService,
    RegisterPersonalService,
    RegisterService,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.business_profile import (
    SqlAlchemyBusinessRegistrationRepository,
)
from app.infrastructure.repository.device import SqlAlchemyUserDeviceRepository
from app.infrastructure.repository.person_profile import (
    SqlAlchemyPersonRegistrationRepository,
)
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.presentation.dtos import (
    AuthOutput,
    LoginRequest,
    RegisterDeviceInput,
    RegisterDeviceOutput,
    RegisterRequest,
    UserOutput,
)
from app.presentation.mappers import DeviceMapper, UserMapper

router = APIRouter(tags=["Authentication"])
bearer_scheme = HTTPBearer(
    scheme_name="BearerToken",
    description="Paste an existing JWT access token.",
    auto_error=False,
)


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    return AuthService(
        repository=SqlAlchemyUserRepository(db),
        jwt_secret_key=settings.jwt_secret_key,
        jwt_algorithm=settings.jwt_algorithm,
        access_token_expire_minutes=settings.access_token_expire_minutes,
    )


def get_register_service(db: Annotated[Session, Depends(get_db)]) -> RegisterService:
    return RegisterService(
        personal_service=RegisterPersonalService(
            SqlAlchemyPersonRegistrationRepository(db)
        ),
        business_service=RegisterBusinessService(
            SqlAlchemyBusinessRegistrationRepository(db)
        ),
    )


credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_access_token(
    bearer_credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
) -> str:
    if bearer_credentials is not None:
        return bearer_credentials.credentials
    raise credentials_exception


@router.post(
    "/register",
    response_model=AuthOutput,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    register_service: Annotated[RegisterService, Depends(get_register_service)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthOutput:
    registration = UserMapper.to_registration(payload)
    try:
        user = register_service.register(registration)
    except DuplicateEmailError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        ) from error
    except DuplicateCpfError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CPF is already registered",
        ) from error
    except DuplicateCnpjError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CNPJ is already registered",
        ) from error
    except InvalidCpfError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CPF is invalid",
        ) from error
    except InvalidCnpjError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CNPJ is invalid",
        ) from error
    except InvalidCoordinatesError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid coordinates",
        ) from error
    except MinimumAgeError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Minimum age is 18 years",
        ) from error

    token = auth_service.create_access_token(user)
    return AuthAssembler.to_auth_dto(user, token)


@router.post("/login", response_model=AuthOutput)
def login(
    payload: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthOutput:
    try:
        user = auth_service.authenticate(
            payload.email, payload.password.get_secret_value()
        )
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        ) from error
    except AccountDeletedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been deleted",
        ) from error

    token = auth_service.create_access_token(user)
    return AuthAssembler.to_auth_dto(user, token)


def get_current_user(
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    """Resolve the bearer token into the user every protected route needs."""
    try:
        return auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error


@router.get("/users/me", response_model=UserOutput)
def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserOutput:
    return AuthAssembler.to_user_dto(current_user)


def get_device_service(db: Annotated[Session, Depends(get_db)]) -> DeviceService:
    return DeviceService(repository=SqlAlchemyUserDeviceRepository(db))


@router.post(
    "/users/me/devices",
    response_model=RegisterDeviceOutput,
    status_code=status.HTTP_201_CREATED,
    tags=["Devices"],
)
def register_device(
    payload: RegisterDeviceInput,
    current_user: Annotated[User, Depends(get_current_user)],
    device_service: Annotated[DeviceService, Depends(get_device_service)],
) -> RegisterDeviceOutput:
    device = DeviceMapper.to_entity(payload, current_user.user_id)
    try:
        result = device_service.register(device)
    except InvalidDeviceTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid device token format",
        ) from error
    return DeviceAssembler.to_dto(result)
