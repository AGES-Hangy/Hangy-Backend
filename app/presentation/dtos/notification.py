from pydantic import BaseModel


class UnreadNotificationCountOutput(BaseModel):
    unread_count: int
