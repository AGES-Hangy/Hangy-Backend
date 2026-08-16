from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class UserCredentials:
    username: str
    password: str


@dataclass(frozen=True, slots=True)
class User:
    id: int | None
    username: str
    password_hash: str
    created_at: datetime
