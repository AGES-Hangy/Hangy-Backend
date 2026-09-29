from pydantic import BaseModel, ConfigDict, Field, SecretStr

__all__ = [
    "PasswordResetConfirmInput",
    "PasswordResetRequestInput",
    "VerifyResetCodeRequest",
    "VerifyResetCodeResponse",
]


class PasswordResetConfirmInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reset_token: str = Field(min_length=1, max_length=2048)
    new_password: SecretStr = Field(min_length=8, max_length=128)


class PasswordResetRequestInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: str = Field(
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )


class VerifyResetCodeRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: str = Field(
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    code: str = Field(pattern=r"^\d{6}$")


class VerifyResetCodeResponse(BaseModel):
    reset_token: str
    expires_in: int
