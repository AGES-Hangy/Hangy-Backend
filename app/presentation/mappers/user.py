from app.domain.entities import UserCredentials
from app.presentation.dtos import RegisterInput


class UserMapper:
    @staticmethod
    def to_credentials(dto: RegisterInput) -> UserCredentials:
        return UserCredentials(
            username=dto.username,
            password=dto.password.get_secret_value(),
        )
