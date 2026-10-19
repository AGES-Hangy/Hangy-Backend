from pydantic import BaseModel

__all__ = ["EventCoverUploadOutput"]


class EventCoverUploadOutput(BaseModel):
    cover_photo_url: str
