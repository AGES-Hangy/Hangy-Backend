from pydantic import BaseModel, ConfigDict, Field

__all__ = ["PasswordResetRequestInput"]


class PasswordResetRequestInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: str = Field(
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
