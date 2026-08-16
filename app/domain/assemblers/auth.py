from app.domain.entities import AccessToken, User
from app.presentation.dtos import TokenOutput, UserOutput


class AuthAssembler:
    @staticmethod
    def to_token_dto(token: AccessToken) -> TokenOutput:
        return TokenOutput(
            access_token=token.value,
            token_type=token.token_type.value,
        )

    @staticmethod
    def to_user_dto(user: User) -> UserOutput:
        if user.id is None:
            raise ValueError("A persisted user must have an id")
        return UserOutput(
            id=user.id,
            username=user.username,
            created_at=user.created_at,
        )
