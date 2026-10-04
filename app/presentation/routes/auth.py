from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.assemblers import (
    AuthAssembler,
    DeviceAssembler,
    PasswordResetAssembler,
    UserProfileAssembler,
)
from app.domain.entities import User
from app.domain.services import (
    AccountDeletedError,
    AuthService,
    DeviceNotFoundError,
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
    InvalidResetCodeError,
    InvalidResetTokenError,
    MinimumAgeError,
    PasswordResetService,
    RegisterBusinessService,
    RegisterPersonalService,
    RegisterService,
    TooManyPasswordResetRequestsError,
    TooManyResetCodeAttemptsError,
    UserNotFoundError,
    UserProfileService,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.business_profile import (
    SqlAlchemyBusinessRegistrationRepository,
)
from app.infrastructure.repository.device import SqlAlchemyUserDeviceRepository
from app.infrastructure.repository.password_reset_token import (
    SqlAlchemyPasswordResetTokenRepository,
)
from app.infrastructure.repository.person_profile import (
    SqlAlchemyPersonRegistrationRepository,
)
from app.infrastructure.repository.user import SqlAlchemyUserRepository
from app.infrastructure.repository.user_profile import SqlAlchemyUserProfileRepository
from app.presentation.dtos import (
    AuthOutput,
    LoginRequest,
    PasswordResetConfirmInput,
    PasswordResetRequestInput,
    RegisterDeviceInput,
    RegisterDeviceOutput,
    RegisterRequest,
    UserOutput,
    UserProfileOutput,
    VerifyResetCodeRequest,
    VerifyResetCodeResponse,
)
from app.presentation.mappers import (
    DeviceMapper,
    PasswordResetMapper,
    UserMapper,
)

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
        password_reset_token_expire_minutes=(
            settings.password_reset_token_expire_minutes
        ),
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


def get_password_reset_service(
    db: Annotated[Session, Depends(get_db)],
) -> PasswordResetService:
    return PasswordResetService(
        repository=SqlAlchemyPasswordResetTokenRepository(db),
        jwt_secret_key=settings.jwt_secret_key,
        jwt_algorithm=settings.jwt_algorithm,
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
    "/auth/register",
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


@router.post("/auth/login", response_model=AuthOutput)
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


@router.post(
    "/auth/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
)
def request_password_reset(
    payload: PasswordResetRequestInput,
    password_reset_service: Annotated[
        PasswordResetService, Depends(get_password_reset_service)
    ],
) -> Response:
    request = PasswordResetMapper.to_request(payload)
    try:
        password_reset_service.request_password_reset(request)
    except TooManyPasswordResetRequestsError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many reset requests",
        ) from error
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/auth/password-reset/verify",
    response_model=VerifyResetCodeResponse,
    status_code=status.HTTP_200_OK,
)
def verify_password_reset_code(
    payload: VerifyResetCodeRequest,
    password_reset_service: Annotated[
        PasswordResetService, Depends(get_password_reset_service)
    ],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> VerifyResetCodeResponse:
    verification = PasswordResetMapper.to_verification(payload)
    try:
        token = password_reset_service.verify_code(verification)
    except TooManyResetCodeAttemptsError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts",
        ) from error
    except InvalidResetCodeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code",
        ) from error

    reset_token = auth_service.create_reset_token(token)
    return PasswordResetAssembler.to_verify_dto(reset_token)


@router.post(
    "/auth/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid or expired reset token"}
    },
)
def confirm_password_reset(
    payload: PasswordResetConfirmInput,
    password_reset_service: Annotated[
        PasswordResetService, Depends(get_password_reset_service)
    ],
) -> Response:
    confirmation = PasswordResetMapper.to_confirmation(payload)
    try:
        password_reset_service.confirm_password_reset(confirmation)
    except InvalidResetTokenError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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


def get_user_profile_service(
    db: Annotated[Session, Depends(get_db)],
) -> UserProfileService:
    return UserProfileService(repository=SqlAlchemyUserProfileRepository(db))


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


@router.delete(
    "/users/me/devices/{device_token}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Devices"],
)
def remove_device(
    device_token: str,
    current_user: Annotated[User, Depends(get_current_user)],
    device_service: Annotated[DeviceService, Depends(get_device_service)],
) -> None:
    try:
        device_service.remove_token(current_user.user_id, device_token)
    except DeviceNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        ) from error


@router.get(
    "/users/me/profile",
    response_model=UserProfileOutput,
    tags=["Profile"],
)
def read_current_user_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    profile_service: Annotated[UserProfileService, Depends(get_user_profile_service)],
) -> UserProfileOutput:
    try:
        profile = profile_service.get_profile(current_user.user_id)
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from error
    return UserProfileAssembler.to_dto(profile)
