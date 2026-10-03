from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.user_model import user_follows

__all__ = ["UserFollowModel"]


class UserFollowModel(Base):
    """ORM mapping of the ``user_follows`` join table.

    The table itself is declared in ``user_model`` because the ``followers`` /
    ``followed_businesses`` relationships use it as their ``secondary``. Its
    ``followed_business_id`` FK points at ``business_profile.user_id`` (not
    ``user``), so the database itself rejects following a personal profile.
    """

    __table__ = user_follows
