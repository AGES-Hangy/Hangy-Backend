from app.domain.entities import AccessToken, User
from app.domain.enums import UserTypeEnum
from app.presentation.dtos import (
    RegisterBusinessUserOutput,
    RegisterOutput,
    RegisterPersonalUserOutput,
    TokenOutput,
    UserOutput,
)


class AuthAssembler:
    @staticmethod
    def to_token_dto(token: AccessToken) -> TokenOutput:
        return TokenOutput(
            access_token=token.value,
            token_type=token.token_type.value,
        )

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
    def to_register_dto(user: User, token: AccessToken) -> RegisterOutput:
        if user.user_id is None:
            raise ValueError("A persisted user must have an id")

        user_dto: RegisterPersonalUserOutput | RegisterBusinessUserOutput
        if user.user_type == UserTypeEnum.PERSONAL:
            user_dto = RegisterPersonalUserOutput(
                id=user.user_id,
                email=user.email,
                user_type=UserTypeEnum.PERSONAL,
                name=user.name or "",
            )
        else:
            user_dto = RegisterBusinessUserOutput(
                id=user.user_id,
                email=user.email,
                user_type=UserTypeEnum.BUSINESS,
                business_name=user.name or "",
            )
        return RegisterOutput(
            access_token=token.value,
            token_type=token.token_type.value,
            user=user_dto,
        )
