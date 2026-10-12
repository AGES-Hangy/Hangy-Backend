from uuid import UUID

from app.domain.entities import EventExperience
from app.presentation.dtos import CreateExperienceOutput

__all__ = ["ExperienceAssembler"]


class ExperienceAssembler:
    @staticmethod
    def to_created_dto(
        experience: EventExperience, event_id: UUID
    ) -> CreateExperienceOutput:
        if experience.experience_id is None:
            raise ValueError("A persisted experience must have an id")
        return CreateExperienceOutput(
            experience_id=experience.experience_id,
            event_id=event_id,
            description=experience.description,
            images=[],
            created_at=experience.created_at,
        )
