from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["CreateExperienceInput", "CreateExperienceOutput", "ExperienceImageOutput"]


class CreateExperienceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(min_length=1, max_length=1000)


class ExperienceImageOutput(BaseModel):
    photo_id: UUID
    photo_url: str
    created_at: datetime


class CreateExperienceOutput(BaseModel):
    experience_id: UUID
    event_id: UUID
    description: str
    images: list[ExperienceImageOutput]
    created_at: datetime
