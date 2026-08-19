from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class RegisterInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9_.-]+$",
    )
    password: SecretStr = Field(min_length=8, max_length=128)


class UserOutput(BaseModel):
    id: int
    username: str
    created_at: datetime


class TokenOutput(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
