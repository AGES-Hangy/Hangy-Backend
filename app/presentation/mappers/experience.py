from app.domain.entities import NewEventExperience
from app.presentation.dtos import CreateExperienceInput

__all__ = ["ExperienceMapper"]


class ExperienceMapper:
    @staticmethod
    def to_new_experience(dto: CreateExperienceInput) -> NewEventExperience:
        return NewEventExperience(description=dto.description)
