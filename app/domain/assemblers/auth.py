from app.domain.entities import AccessToken, BusinessProfile, PersonProfile, User
from app.domain.enums import UserTypeEnum
from app.presentation.dtos import (
    AuthBusinessUserOutput,
    AuthOutput,
    AuthPersonalUserOutput,
    BusinessProfileOutput,
    CurrentUserOutput,
    PersonalProfileOutput,
)


class AuthAssembler:
    @staticmethod
    def to_current_user_dto(
        user: User, profile: PersonProfile | BusinessProfile | None
    ) -> CurrentUserOutput:
        if user.user_id is None:
            raise ValueError("A persisted user must have an id")

        profile_dto: PersonalProfileOutput | BusinessProfileOutput | None = None
        if isinstance(profile, PersonProfile):
            profile_dto = PersonalProfileOutput(
                date_of_birth=profile.date_of_birth,
                city=profile.city,
                state=profile.state,
                photo_url=user.profile_photo_url,
            )
        elif isinstance(profile, BusinessProfile):
            profile_dto = BusinessProfileOutput(
                cnpj=profile.cnpj,
                address=profile.address,
                latitude=profile.business_latitude,
                longitude=profile.business_longitude,
                photo_url=user.profile_photo_url,
            )

        return CurrentUserOutput(
            id=user.user_id,
            email=user.email,
            user_type=user.user_type,
            name=user.name,
            profile=profile_dto,
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
