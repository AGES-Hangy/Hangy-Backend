from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordBearer,
)
from sqlalchemy.orm import Session

from app.config import settings
from app.domain.entities import User
from app.domain.services import (
    AuthService,
    InvalidAccessTokenError,
)
from app.infrastructure.repository import get_db
from app.infrastructure.repository.user import SqlAlchemyUserRepository

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="login",
    scheme_name="OAuth2Password",
    auto_error=False,
)
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


credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_access_token(
    oauth2_token: Annotated[str | None, Security(oauth2_scheme)],
    bearer_credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
) -> str:
    if oauth2_token is not None:
        return oauth2_token
    if bearer_credentials is not None:
        return bearer_credentials.credentials
    raise credentials_exception


def get_current_user(
    token: Annotated[str, Depends(get_access_token)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> User:
    """Resolve the bearer token into the user every protected route needs."""
    try:
        return auth_service.get_user_from_token(token)
    except InvalidAccessTokenError as error:
        raise credentials_exception from error
