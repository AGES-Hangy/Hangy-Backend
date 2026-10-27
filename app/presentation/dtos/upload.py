from pydantic import BaseModel

__all__ = ["EventCoverUploadOutput", "ProfilePhotoOutput"]


class EventCoverUploadOutput(BaseModel):
    cover_photo_url: str


class ProfilePhotoOutput(BaseModel):
    photo_url: str
