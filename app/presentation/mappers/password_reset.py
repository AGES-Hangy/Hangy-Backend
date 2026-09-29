from app.domain.entities import PasswordResetRequest, VerifyResetCode
from app.presentation.dtos import PasswordResetRequestInput, VerifyResetCodeRequest

__all__ = ["PasswordResetMapper"]


class PasswordResetMapper:
    @staticmethod
    def to_request(payload: PasswordResetRequestInput) -> PasswordResetRequest:
        return PasswordResetRequest(email=payload.email)

    @staticmethod
    def to_verification(payload: VerifyResetCodeRequest) -> VerifyResetCode:
        return VerifyResetCode(email=payload.email, code=payload.code)
