from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "PasswordResetRequestInput",
    "VerifyResetCodeRequest",
    "VerifyResetCodeResponse",
]


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
