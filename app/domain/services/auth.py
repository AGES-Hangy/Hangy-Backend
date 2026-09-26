from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.domain.entities import AccessToken, User

password_hash = PasswordHash.recommended()


class UserRepository(Protocol):
    def get_by_id(self, user_id: UUID) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...


class DuplicateEmailError(Exception):
    """Raised when an email is already registered."""


class InvalidAccessTokenError(Exception):
    """Raised when an access token is invalid or references no user."""


class InvalidCredentialsError(Exception):
    """Raised when the email/password pair does not match any account."""


class AccountDeletedError(Exception):
    """Raised when the credentials are correct but the account was deleted."""


class AuthService:
    def __init__(
        self,
        repository: UserRepository,
        jwt_secret_key: str,
        jwt_algorithm: str,
        access_token_expire_minutes: int,
    ) -> None:
        self.repository = repository
        self.jwt_secret_key = jwt_secret_key
        self.jwt_algorithm = jwt_algorithm
        self.access_token_expire_minutes = access_token_expire_minutes

    def authenticate(self, email: str, password: str) -> User:
        user = self.repository.get_by_email(email)
        # Same error for "no such email" and "wrong password" so a caller
        # can't use it to probe which emails have an account.
        if user is None or not password_hash.verify(password, user.password_hash):
            raise InvalidCredentialsError
        if user.deleted_at is not None:
            raise AccountDeletedError
        return user

    def create_access_token(self, user: User) -> AccessToken:
        if user.user_id is None:
            raise ValueError("A persisted user must have an id")

        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(minutes=self.access_token_expire_minutes)
        encoded_jwt = jwt.encode(
            {"sub": str(user.user_id), "iat": issued_at, "exp": expires_at},
            self.jwt_secret_key,
            algorithm=self.jwt_algorithm,
        )
        return AccessToken(value=encoded_jwt)

    def get_user_from_token(self, token: str) -> User:
        try:
            payload = jwt.decode(
                token,
                self.jwt_secret_key,
                algorithms=[self.jwt_algorithm],
            )
            subject = payload.get("sub")
            if not isinstance(subject, str):
                raise InvalidAccessTokenError
            user_id = UUID(subject)
            issued_at = payload.get("iat")
        except (jwt.InvalidTokenError, ValueError) as error:
            raise InvalidAccessTokenError from error

        user = self.repository.get_by_id(user_id)
        if user is None:
            raise InvalidAccessTokenError
        # A token with no "iat" carries no freshness info to check, so it is
        # left alone here (e.g. tokens minted before this claim existed).
        if (
            isinstance(issued_at, int)
            and user.password_changed_at is not None
            and issued_at < int(_as_utc(user.password_changed_at).timestamp())
        ):
            raise InvalidAccessTokenError
        return user


def _as_utc(value: datetime) -> datetime:
    """SQLite drops tzinfo on read; treat naive datetimes as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
