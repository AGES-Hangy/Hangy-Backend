from app.domain.entities import ResetToken
from app.presentation.dtos import VerifyResetCodeResponse

__all__ = ["PasswordResetAssembler"]


class PasswordResetAssembler:
    @staticmethod
    def to_verify_dto(token: ResetToken) -> VerifyResetCodeResponse:
        return VerifyResetCodeResponse(
            reset_token=token.value,
            expires_in=token.expires_in,
        )
