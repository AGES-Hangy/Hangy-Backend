from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from typing import Optional
from app.domain.enums import UserTypeEnum, UserRoleEnum

@dataclass
class User:
    user_id: UUID
    user_type: UserTypeEnum
    role: UserRoleEnum
    email: str
    password_hash: str
    user_phone: Optional[str] = None
    profile_photo_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime    
    deleted_at: Optional[datetime] = None