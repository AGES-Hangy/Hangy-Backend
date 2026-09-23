from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(kw_only=True)
class Device:
    device_token: str
    user_id: UUID
    created_at: datetime
    updated_at: datetime


__all__ = ["Device"]
