from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UserPhotoEventOutput(BaseModel):
    id: UUID
    title: str


class UserPhotoOutput(BaseModel):
    photo_id: UUID
    photo_url: str
    event: UserPhotoEventOutput
    created_at: datetime


class UserPhotosOutput(BaseModel):
    items: list[UserPhotoOutput]
    next_cursor: str | None
