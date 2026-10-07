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
    DeleteAccountService,
    DescriptionTooLongError,
    DeviceNotFoundError,
    DeviceService,
    DuplicateCnpjError,
    DuplicateCpfError,
    DuplicateEmailError,
    HasFutureEventsError,
    InvalidAccessTokenError,
    InvalidCnpjError,
    InvalidCoordinatesError,
    InvalidCpfError,
    InvalidCredentialsError,
    InvalidDeviceTokenError,
    InvalidResetCodeError,
    InvalidResetTokenError,
    MinimumAgeError,
    NotAPersonalProfileError,
    PasswordConfirmationError,
    PasswordResetService,
    RegisterBusinessService,
    RegisterPersonalService,
    RegisterService,
    TooManyPasswordResetRequestsError,
    TooManyResetCodeAttemptsError,
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
from app.infrastructure.repository.user_tags import SqlAlchemyUserTagsRepository
from app.presentation.dtos import (
    AuthOutput,
    CurrentUserOutput,
    DeleteAccountInput,
    LoginRequest,
    PasswordResetConfirmInput,
    PasswordResetRequestInput,
    RegisterDeviceInput,
    RegisterDeviceOutput,
    RegisterRequest,
    UserProfileOutput,
    UserProfileUpdateInput,
    UserProfileUpdateOutput,
    VerifyResetCodeRequest,
    VerifyResetCodeResponse,
)
from app.presentation.mappers import (
    DeviceMapper,
    PasswordResetMapper,
    UserMapper,
    UserProfileMapper,
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


def get_user_profile_service(
    db: Annotated[Session, Depends(get_db)],
) -> UserProfileService:
    return UserProfileService(
        repository=SqlAlchemyUserProfileRepository(db),
        tags_repository=SqlAlchemyUserTagsRepository(db),
        description_max_length=settings.profile_description_max_length,
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
    except AccountDeletedError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been deleted",
        ) from error
    except InvalidAccessTokenError as error:
        raise credentials_exception from error


@router.get(
    "/users/me",
    response_model=CurrentUserOutput,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": (
                "Token ausente, invalido, expirado ou emitido antes da "
                "ultima troca de senha."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "A conta associada ao token foi excluida.",
            "content": {
                "application/json": {"example": {"detail": "Account has been deleted"}}
            },
        },
    },
)
def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
    user_profile_service: Annotated[
        UserProfileService, Depends(get_user_profile_service)
    ],
) -> CurrentUserOutput:
    profile = user_profile_service.get_profile_for_user(current_user)
    return AuthAssembler.to_current_user_dto(current_user, profile)


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
    status_code=status.HTTP_200_OK,
    tags=["Profile"],
    summary="Perfil do usuario autenticado com os contadores das abas",
    description=(
        "Retorna os dados do perfil (com as tags de interesse ordenadas pela "
        "macro e depois pelo nome) e os contadores das abas. `confirmed` conta "
        "participacoes CONFIRMED em eventos PUBLISHED que ainda nao terminaram; "
        "`past` conta participacoes CONFIRMED em eventos terminados (`ends_at` "
        "ja passou ou status FINISHED); eventos cancelados ou excluidos nao "
        "entram. `photos` conta as imagens das experiencias do proprio usuario. "
        "`photo_url` vem `null` quando o usuario nao tem foto."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": (
                "Token ausente, invalido, expirado ou emitido antes da "
                "ultima troca de senha."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "A conta associada ao token foi excluida.",
            "content": {
                "application/json": {"example": {"detail": "Account has been deleted"}}
            },
        },
    },
)
def read_current_user_profile(
    current_user: Annotated[User, Depends(get_current_user)],
    user_profile_service: Annotated[
        UserProfileService, Depends(get_user_profile_service)
    ],
) -> UserProfileOutput:
    profile = user_profile_service.get_profile(current_user)
    return UserProfileAssembler.to_dto(profile)


@router.patch(
    "/users/me/profile",
    response_model=UserProfileUpdateOutput,
    status_code=status.HTTP_200_OK,
    tags=["Profile"],
    summary="Editar o perfil pessoal do usuario autenticado",
    description=(
        "Atualizacao parcial: so os campos enviados mudam. `description` pode "
        "ser `null` para limpar a bio; `name`, `state` e `city` nao. CPF, "
        "e-mail, data de nascimento e qualquer outro campo desconhecido sao "
        "ignorados. `updated_at` so muda quando algum valor realmente muda. "
        "Apenas contas PERSONAL possuem perfil pessoal."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "description": (
                "A bio passou do limite configurado em PROFILE_DESCRIPTION_MAX_LENGTH."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Description exceeds maximum length"}
                }
            },
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": (
                "Token ausente, invalido, expirado ou emitido antes da "
                "ultima troca de senha."
            ),
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": (
                "A conta e comercial (`Not a personal profile`) ou foi "
                "excluida (`Account has been deleted`)."
            ),
            "content": {
                "application/json": {"example": {"detail": "Not a personal profile"}}
            },
        },
    },
)
def update_current_user_profile(
    payload: UserProfileUpdateInput,
    current_user: Annotated[User, Depends(get_current_user)],
    user_profile_service: Annotated[
        UserProfileService, Depends(get_user_profile_service)
    ],
) -> UserProfileUpdateOutput:
    update = UserProfileMapper.to_update(payload)
    try:
        profile = user_profile_service.update_profile(current_user, update)
    except NotAPersonalProfileError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a personal profile",
        ) from error
    except DescriptionTooLongError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Description exceeds maximum length",
        ) from error
    return UserProfileAssembler.to_update_dto(profile)


def get_delete_account_service(
    db: Annotated[Session, Depends(get_db)],
) -> DeleteAccountService:
    return DeleteAccountService(repository=SqlAlchemyUserRepository(db))


@router.delete(
    "/users/me",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Token ausente, invalido ou expirado.",
            "content": {
                "application/json": {
                    "example": {"detail": "Could not validate credentials"}
                }
            },
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Senha incorreta.",
            "content": {
                "application/json": {
                    "example": {"detail": "Password confirmation failed"}
                }
            },
        },
        status.HTTP_409_CONFLICT: {
            "description": "Usuario organiza eventos futuros.",
            "content": {
                "application/json": {
                    "example": {"detail": "Account has future events as organizer"}
                }
            },
        },
    },
)
def delete_account(
    payload: DeleteAccountInput,
    current_user: Annotated[User, Depends(get_current_user)],
    delete_service: Annotated[
        DeleteAccountService, Depends(get_delete_account_service)
    ],
) -> Response:
    try:
        delete_service.delete_account(current_user, payload.password.get_secret_value())
    except PasswordConfirmationError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password confirmation failed",
        ) from error
    except HasFutureEventsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account has future events as organizer",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
