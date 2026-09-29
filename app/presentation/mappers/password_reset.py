from app.domain.entities import PasswordResetRequest
from app.presentation.dtos import PasswordResetRequestInput

__all__ = ["PasswordResetMapper"]


class PasswordResetMapper:
    @staticmethod
    def to_request(payload: PasswordResetRequestInput) -> PasswordResetRequest:
        return PasswordResetRequest(email=payload.email)
