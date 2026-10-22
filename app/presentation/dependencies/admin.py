__all__ = ["require_admin"]

from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.domain.entities import User
from app.domain.enums import UserRoleEnum
from app.presentation.routes.auth import get_current_user


def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """Resolve the bearer token and reject anyone who is not an admin.

    Reused by every /admin/* route: 401 comes from get_current_user, 403 from here.
    """
    if current_user.role != UserRoleEnum.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user