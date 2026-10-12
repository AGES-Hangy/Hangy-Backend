from app.domain.entities import PersonProfileUpdate
from app.presentation.dtos import UserProfileUpdateInput


class UserProfileMapper:
    @staticmethod
    def to_update(dto: UserProfileUpdateInput) -> PersonProfileUpdate:
        # Only the fields the client actually sent; the rest stay unchanged.
        return PersonProfileUpdate(**dto.model_dump(exclude_unset=True))
