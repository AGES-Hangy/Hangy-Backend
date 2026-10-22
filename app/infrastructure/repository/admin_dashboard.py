from datetime import UTC, datetime

from sqlalchemy import false, func, or_, select, true
from sqlalchemy.orm import Session, aliased

from app.domain.entities import (
    DashboardRecentReport,
    DashboardReportCounts,
    DashboardUserCounts,
)
from app.domain.enums import ReportStatusEnum, UserTypeEnum
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel


class SqlAlchemyAdminDashboardRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_report_counts(self, opened_since: datetime) -> DashboardReportCounts:
        pending = ReportModel.status == ReportStatusEnum.PENDING
        row = self.db.execute(
            select(
                func.count().filter(pending),
                # The report has no created_at column yet; for a PENDING report
                # updated_at is still the moment it was opened.
                func.count().filter(pending, ReportModel.updated_at >= opened_since),
                func.count().filter(ReportModel.status == ReportStatusEnum.REVIEWED),
            ).where(ReportModel.deleted_at.is_(None))
        ).one()
        return DashboardReportCounts(
            open=row[0],
            open_last_24h=row[1],
            in_review=row[2],
            # TODO: report has no reviewer column yet, so there is nothing to
            # count. Replace with COUNT(DISTINCT reviewer) once it exists.
            in_review_moderators=0,
        )

    def get_user_counts(
        self,
        now: datetime,
        created_since: datetime,
        end_of_today: datetime,
    ) -> DashboardUserCounts:
        # user.suspended_until is created by task 249. Until it is merged the
        # column does not exist, so nobody counts as suspended.
        suspended_until = getattr(UserModel, "suspended_until", None)

        if suspended_until is None:
            not_suspended = true()
            suspended = false()
            expiring_today = false()
        else:
            not_suspended = or_(suspended_until.is_(None), suspended_until <= now)
            suspended = suspended_until > now
            expiring_today = (suspended_until > now) & (suspended_until <= end_of_today)

        row = self.db.execute(
            select(
                func.count().filter(not_suspended),
                func.count().filter(
                    not_suspended, UserModel.created_at >= created_since
                ),
                func.count().filter(suspended),
                func.count().filter(expiring_today),
            ).where(UserModel.deleted_at.is_(None))
        ).one()
        return DashboardUserCounts(
            active=row[0],
            active_new_this_week=row[1],
            suspended=row[2],
            suspended_expiring_today=row[3],
        )

    def list_recent_reports(
        self, statuses: tuple[ReportStatusEnum, ...], limit: int
    ) -> list[DashboardRecentReport]:
        sibling = aliased(ReportModel)
        report_count = (
            select(func.count())
            .select_from(sibling)
            .where(
                sibling.deleted_at.is_(None),
                or_(
                    sibling.reported_user_id == ReportModel.reported_user_id,
                    sibling.reported_event_id == ReportModel.reported_event_id,
                ),
            )
            .correlate(ReportModel)
            .scalar_subquery()
        )
        rows = self.db.execute(
            select(
                ReportModel,
                UserModel.name,
                UserModel.user_type,
                EventModel.event_title,
                report_count,
            )
            .outerjoin(UserModel, UserModel.user_id == ReportModel.reported_user_id)
            .outerjoin(EventModel, EventModel.event_id == ReportModel.reported_event_id)
            .where(ReportModel.deleted_at.is_(None), ReportModel.status.in_(statuses))
            .order_by(ReportModel.updated_at.desc(), ReportModel.report_id.desc())
            .limit(limit)
        ).all()
        return [
            self._to_entity(model, user_name, user_type, event_title, count)
            for model, user_name, user_type, event_title, count in rows
        ]

    @staticmethod
    def _to_entity(
        model: ReportModel,
        user_name: str | None,
        user_type: UserTypeEnum | None,
        event_title: str | None,
        report_count: int,
    ) -> DashboardRecentReport:
        # SQLite drops tzinfo on read; treat naive datetimes as UTC.
        opened_at = model.updated_at
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=UTC)
        return DashboardRecentReport(
            report_id=model.report_id,
            report_type=model.report_type,
            status=model.status,
            description=model.description,
            opened_at=opened_at,
            report_count=report_count,
            reported_user_name=user_name,
            reported_user_type=user_type,
            reported_event_title=event_title,
        )