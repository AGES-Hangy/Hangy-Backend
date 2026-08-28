from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.domain.entities import AccessToken, User, UserCredentials
from app.domain.enums import UserRoleEnum

password_hash = PasswordHash.recommended()


class UserRepository(Protocol):
    def get_by_id(self, user_id: UUID) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...

    def add(self, user: User) -> User: ...


class DuplicateEmailError(Exception):
    """Raised when an email is already registered."""


class InvalidAccessTokenError(Exception):
    """Raised when an access token is invalid or references no user."""


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

    def register(self, credentials: UserCredentials) -> User:
        if self.repository.get_by_email(credentials.email) is not None:
            raise DuplicateEmailError

        now = datetime.now(UTC)
        user = User(
            user_id=None,
            user_type=credentials.user_type,
            email=credentials.email,
            password_hash=password_hash.hash(credentials.password),
            created_at=now,
            updated_at=now,
            role=UserRoleEnum.USER,
        )
        return self.repository.add(user)

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.repository.get_by_email(email)
        if user is None or not password_hash.verify(password, user.password_hash):
            return None
        return user

    def create_access_token(self, user: User) -> AccessToken:
        if user.user_id is None:
            raise ValueError("A persisted user must have an id")

        expires_at = datetime.now(UTC) + timedelta(
            minutes=self.access_token_expire_minutes
        )
        encoded_jwt = jwt.encode(
            {"sub": str(user.user_id), "exp": expires_at},
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
        except (jwt.InvalidTokenError, ValueError) as error:
            raise InvalidAccessTokenError from error

        user = self.repository.get_by_id(user_id)
        if user is None:
            raise InvalidAccessTokenError
        return user
