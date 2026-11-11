from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, and_, false, func, null, or_, select, true
from sqlalchemy.orm import Session, aliased

from app.domain.entities import (
    AdminModerationActor,
    AdminModerationEntry,
    AdminUserDetailRecord,
    AdminUserMetrics,
    AdminUserRecord,
)
from app.domain.enums import (
    AuditActionEnum,
    EventStatusEnum,
    ModerationStatusEnum,
    ReportResolutionActionEnum,
    ReportStatusEnum,
)
from app.infrastructure.repository.models import AuditLogModel, UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel

MODERATION_ACTIONS = (
    AuditActionEnum.USER_BANNED,
    AuditActionEnum.USER_SUSPENDED,
    AuditActionEnum.USER_REVERTED,
)
UPHELD_ACTIONS = (
    ReportResolutionActionEnum.BANNED,
    ReportResolutionActionEnum.SUSPENDED,
)
MODERATION_HISTORY_LIMIT = 50


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
        # (personal or business) or one of the events they created. Archived
        # reports (task 246: status REJECTED) do not count.
        report_count = (
            select(func.count())
            .select_from(ReportModel)
            .outerjoin(EventModel, EventModel.event_id == ReportModel.reported_event_id)
            .where(
                ReportModel.deleted_at.is_(None),
                ReportModel.status != ReportStatusEnum.REJECTED,
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

    def get_detail(self, user_id: UUID) -> AdminUserDetailRecord | None:
        model = self.db.scalar(
            select(UserModel).where(
                UserModel.user_id == user_id, UserModel.deleted_at.is_(None)
            )
        )
        if model is None:
            return None
        return self._to_detail_record(
            model, self._metrics(user_id), self._history(user_id)
        )

    def _metrics(self, user_id: UUID) -> AdminUserMetrics:
        event_count, event_cancelled_count = self.db.execute(
            select(
                func.count(),
                func.count().filter(
                    EventModel.event_status == EventStatusEnum.CANCELLED
                ),
            ).where(
                EventModel.event_creator_id == user_id,
                EventModel.deleted_at.is_(None),
            )
        ).one()
        report_count, report_upheld_count = self.db.execute(
            select(
                func.count(),
                func.count().filter(ReportModel.resolution_action.in_(UPHELD_ACTIONS)),
            )
            .select_from(ReportModel)
            .outerjoin(EventModel, EventModel.event_id == ReportModel.reported_event_id)
            .where(
                ReportModel.deleted_at.is_(None),
                ReportModel.status != ReportStatusEnum.REJECTED,
                or_(
                    ReportModel.reported_user_id == user_id,
                    EventModel.event_creator_id == user_id,
                ),
            )
        ).one()
        return AdminUserMetrics(
            event_count=event_count,
            event_cancelled_count=event_cancelled_count,
            report_count=report_count,
            report_upheld_count=report_upheld_count,
        )

    def _history(self, user_id: UUID) -> tuple[AdminModerationEntry, ...]:
        actor = aliased(UserModel)
        report = aliased(ReportModel)
        rows = self.db.execute(
            select(AuditLogModel, actor.user_id, actor.name, report.report_id)
            .outerjoin(actor, actor.user_id == AuditLogModel.actor_id)
            .outerjoin(
                report,
                and_(
                    report.reported_user_id == AuditLogModel.target_id,
                    report.resolved_by_id == AuditLogModel.actor_id,
                    report.resolved_at == AuditLogModel.created_at,
                ),
            )
            .where(
                AuditLogModel.target_id == user_id,
                AuditLogModel.action.in_(MODERATION_ACTIONS),
            )
            .order_by(AuditLogModel.created_at.desc(), AuditLogModel.audit_id.desc())
            .limit(MODERATION_HISTORY_LIMIT)
        ).all()
        return tuple(
            AdminModerationEntry(
                action=log.action,
                actor=(
                    AdminModerationActor(user_id=actor_id, name=actor_name)
                    if actor_id is not None
                    else None
                ),
                occurred_at=log.created_at,
                report_id=report_id,
            )
            for log, actor_id, actor_name, report_id in rows
        )

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

    @staticmethod
    def _to_detail_record(
        model: UserModel,
        metrics: AdminUserMetrics,
        history: tuple[AdminModerationEntry, ...],
    ) -> AdminUserDetailRecord:
        return AdminUserDetailRecord(
            user_id=model.user_id,
            name=model.name,
            email=model.email,
            created_at=model.created_at,
            banned_at=model.banned_at,
            suspended_until=model.suspended_until,
            metrics=metrics,
            history=history,
        )