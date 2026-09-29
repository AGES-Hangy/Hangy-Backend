from app.domain.entities import (
    PasswordResetConfirmation,
    PasswordResetRequest,
    VerifyResetCode,
)
from app.presentation.dtos import (
    PasswordResetConfirmInput,
    PasswordResetRequestInput,
    VerifyResetCodeRequest,
)

__all__ = ["PasswordResetMapper"]


class PasswordResetMapper:
    @staticmethod
    def to_request(payload: PasswordResetRequestInput) -> PasswordResetRequest:
        return PasswordResetRequest(email=payload.email)

    @staticmethod
    def to_verification(payload: VerifyResetCodeRequest) -> VerifyResetCode:
        return VerifyResetCode(email=payload.email, code=payload.code)

    @staticmethod
    def to_confirmation(
        payload: PasswordResetConfirmInput,
    ) -> PasswordResetConfirmation:
        return PasswordResetConfirmation(
            reset_token=payload.reset_token,
            new_password=payload.new_password.get_secret_value(),
        )
