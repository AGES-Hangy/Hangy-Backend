from datetime import UTC, datetime, timedelta
from typing import Protocol

import jwt
from pwdlib import PasswordHash

from app.domain.entities import AccessToken, User, UserCredentials

password_hash = PasswordHash.recommended()


class UserRepository(Protocol):
    def get_by_id(self, user_id: int) -> User | None: ...

    def get_by_username(self, username: str) -> User | None: ...

    def add(self, user: User) -> User: ...


class DuplicateUsernameError(Exception):
    """Raised when a username is already registered."""


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
        if self.repository.get_by_username(credentials.username) is not None:
            raise DuplicateUsernameError

        user = User(
            id=None,
            username=credentials.username,
            password_hash=password_hash.hash(credentials.password),
            created_at=datetime.now(UTC),
        )
        return self.repository.add(user)

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.repository.get_by_username(username)
        if user is None or not password_hash.verify(password, user.password_hash):
            return None
        return user

    def create_access_token(self, user: User) -> AccessToken:
        expires_at = datetime.now(UTC) + timedelta(
            minutes=self.access_token_expire_minutes
        )
        encoded_jwt = jwt.encode(
            {"sub": user.username, "exp": expires_at},
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
            username = payload.get("sub")
            if not isinstance(username, str):
                raise InvalidAccessTokenError
        except jwt.InvalidTokenError as error:
            raise InvalidAccessTokenError from error

        user = self.repository.get_by_username(username)
        if user is None:
            raise InvalidAccessTokenError
        return user
