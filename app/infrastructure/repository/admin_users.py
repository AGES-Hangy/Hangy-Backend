from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, null, or_, select, true
from sqlalchemy.orm import Session

from app.domain.entities import AdminUserRecord
from app.domain.enums import ModerationStatusEnum
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel


class SqlAlchemyAdminUsersRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_users(
        self,
        now: datetime,
        status: ModerationStatusEnum | None,
        search: str | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[AdminUserRecord]:
        # user.banned_at and user.suspended_until are created by task 249.
        # Until it is merged the columns do not exist and everyone is ACTIVE.
        banned_at = getattr(UserModel, "banned_at", None)
        suspended_until = getattr(UserModel, "suspended_until", None)

        event_count = (
            select(func.count())
            .select_from(EventModel)
            .where(
                EventModel.event_creator_id == UserModel.user_id,
                EventModel.deleted_at.is_(None),
            )
            .correlate(UserModel)
            .scalar_subquery()
        )
        # A report counts against the user whether it targets their profile
        # (personal or business) or one of the events they created.
        report_count = (
            select(func.count())
            .select_from(ReportModel)
            .outerjoin(EventModel, EventModel.event_id == ReportModel.reported_event_id)
            .where(
                ReportModel.deleted_at.is_(None),
                or_(
                    ReportModel.reported_user_id == UserModel.user_id,
                    EventModel.event_creator_id == UserModel.user_id,
                ),
            )
            .correlate(UserModel)
            .scalar_subquery()
        )

        query = (
            select(
                UserModel,
                banned_at if banned_at is not None else null(),
                suspended_until if suspended_until is not None else null(),
                event_count,
                report_count,
            )
            .where(UserModel.deleted_at.is_(None))
            .order_by(UserModel.created_at.desc(), UserModel.user_id.desc())
            .limit(limit)
        )
        if status is not None:
            query = query.where(
                self._status_filter(status, now, banned_at, suspended_until)
            )
        if search:
            # Escape SQL LIKE wildcards in the raw input so a literal "_" or
            # "%" in the query matches itself instead of any/many characters.
            escaped_search = (
                search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped_search}%"
            query = query.where(
                or_(
                    UserModel.name.ilike(pattern, escape="\\"),
                    UserModel.email.ilike(pattern, escape="\\"),
                )
            )
        if after is not None:
            created_at, user_id = after
            query = query.where(
                or_(
                    UserModel.created_at < created_at,
                    and_(
                        UserModel.created_at == created_at,
                        UserModel.user_id < user_id,
                    ),
                )
            )

        rows = self.db.execute(query).all()
        return [self._to_entity(*row) for row in rows]

    @staticmethod
    def _status_filter(
        status: ModerationStatusEnum,
        now: datetime,
        banned_at,
        suspended_until,
    ) -> ColumnElement[bool]:
        # Mirrors derive_moderation_status in the service.
        if banned_at is None or suspended_until is None:
            return true() if status == ModerationStatusEnum.ACTIVE else false()
        if status == ModerationStatusEnum.BANNED:
            return banned_at.is_not(None)
        if status == ModerationStatusEnum.SUSPENDED:
            return and_(banned_at.is_(None), suspended_until > now)
        return and_(
            banned_at.is_(None),
            or_(suspended_until.is_(None), suspended_until <= now),
        )

    @staticmethod
    def _to_entity(
        model: UserModel,
        banned_at: datetime | None,
        suspended_until: datetime | None,
        event_count: int,
        report_count: int,
    ) -> AdminUserRecord:
        return AdminUserRecord(
            user_id=model.user_id,
            name=model.name,
            created_at=model.created_at,
            banned_at=banned_at,
            suspended_until=suspended_until,
            event_count=event_count,
            report_count=report_count,
        )
