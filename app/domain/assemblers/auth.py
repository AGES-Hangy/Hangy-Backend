from app.domain.entities import AccessToken, User
from app.domain.enums import UserTypeEnum
from app.presentation.dtos import (
    AuthBusinessUserOutput,
    AuthOutput,
    AuthPersonalUserOutput,
    UserOutput,
)


class AuthAssembler:
    @staticmethod
    def to_user_dto(user: User) -> UserOutput:
        if user.user_id is None:
            raise ValueError("A persisted user must have an id")
        return UserOutput(
            user_id=user.user_id,
            email=user.email,
            user_type=user.user_type,
            role=user.role,
            created_at=user.created_at,
        )

    @staticmethod
    def to_auth_dto(user: User, token: AccessToken) -> AuthOutput:
        if user.user_id is None:
            raise ValueError("A persisted user must have an id")

        user_dto: AuthPersonalUserOutput | AuthBusinessUserOutput
        if user.user_type == UserTypeEnum.PERSONAL:
            user_dto = AuthPersonalUserOutput(
                id=user.user_id,
                email=user.email,
                user_type=UserTypeEnum.PERSONAL,
                name=user.name or "",
            )
        else:
            user_dto = AuthBusinessUserOutput(
                id=user.user_id,
                email=user.email,
                user_type=UserTypeEnum.BUSINESS,
                business_name=user.name or "",
            )
        return AuthOutput(
            access_token=token.value,
            token_type=token.token_type.value,
            user=user_dto,
        )
