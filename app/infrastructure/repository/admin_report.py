from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session, aliased

from app.domain.entities import AdminReportDetailRecord, AdminReportQueueItem
from app.domain.enums import ReportStatusEnum
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel

__all__ = ["SqlAlchemyAdminReportsRepository"]


def _target_key(report: type[ReportModel]):
    # A report whose target was deleted keeps its own row instead of merging
    # with every other orphan.
    return func.coalesce(
        report.reported_user_id, report.reported_event_id, report.report_id
    )


def _like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; treat naive datetimes as UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SqlAlchemyAdminReportsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_queue(
        self,
        statuses: tuple[ReportStatusEnum, ...],
        search: str | None,
        report_number: int | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[AdminReportQueueItem]:
        conditions = [
            ReportModel.deleted_at.is_(None),
            ReportModel.status.in_(statuses),
        ]
        if search is not None:
            matching = self._matching_targets(statuses, search, report_number)
            conditions.append(_target_key(ReportModel).in_(matching))

        key = _target_key(ReportModel)
        ranked = (
            select(
                ReportModel.report_id,
                ReportModel.report_number,
                ReportModel.report_type,
                ReportModel.status,
                ReportModel.description,
                ReportModel.created_at,
                ReportModel.reported_user_id,
                ReportModel.reported_event_id,
                func.count().over(partition_by=key).label("report_count"),
                func.row_number()
                .over(
                    partition_by=key,
                    order_by=(
                        ReportModel.created_at.desc(),
                        ReportModel.report_id.desc(),
                    ),
                )
                .label("position"),
            )
            .where(*conditions)
            .subquery()
        )

        query = (
            select(
                ranked,
                UserModel.name,
                UserModel.user_type,
                EventModel.event_title,
            )
            .select_from(ranked)
            .outerjoin(UserModel, UserModel.user_id == ranked.c.reported_user_id)
            .outerjoin(EventModel, EventModel.event_id == ranked.c.reported_event_id)
            .where(ranked.c.position == 1)
            .order_by(ranked.c.created_at.desc(), ranked.c.report_id.desc())
            .limit(limit)
        )
        if after is not None:
            opened_at, report_id = after
            query = query.where(
                or_(
                    ranked.c.created_at < opened_at,
                    and_(
                        ranked.c.created_at == opened_at,
                        ranked.c.report_id < report_id,
                    ),
                )
            )
        return [self._to_queue_item(row) for row in self.db.execute(query).all()]

    @staticmethod
    def _matching_targets(
        statuses: tuple[ReportStatusEnum, ...],
        search: str,
        report_number: int | None,
    ):
        report = aliased(ReportModel)
        pattern = _like_pattern(search)
        clauses = [
            UserModel.name.ilike(pattern, escape="\\"),
            EventModel.event_title.ilike(pattern, escape="\\"),
        ]
        if report_number is not None:
            clauses.append(report.report_number == report_number)
        return (
            select(_target_key(report))
            .select_from(report)
            .outerjoin(UserModel, UserModel.user_id == report.reported_user_id)
            .outerjoin(EventModel, EventModel.event_id == report.reported_event_id)
            .where(
                report.deleted_at.is_(None),
                report.status.in_(statuses),
                or_(*clauses),
            )
        )

    @staticmethod
    def _to_queue_item(row: Row) -> AdminReportQueueItem:
        return AdminReportQueueItem(
            report_id=row.report_id,
            report_number=row.report_number,
            report_type=row.report_type,
            status=row.status,
            description=row.description,
            opened_at=_as_utc(row.created_at),
            report_count=row.report_count,
            reported_user_name=row.name,
            reported_user_type=row.user_type,
            reported_event_title=row.event_title,
        )

    def get_report_detail(self, report_id: UUID) -> AdminReportDetailRecord | None:
        creator_user = aliased(UserModel)
        target_user = aliased(UserModel)

        row = self.db.execute(
            select(ReportModel, creator_user, target_user)
            .join(creator_user, creator_user.user_id == ReportModel.report_creator_id)
            .outerjoin(EventModel, EventModel.event_id == ReportModel.reported_event_id)
            .outerjoin(
                target_user,
                or_(
                    and_(
                        ReportModel.reported_user_id.isnot(None),
                        target_user.user_id == ReportModel.reported_user_id,
                    ),
                    and_(
                        ReportModel.reported_user_id.is_(None),
                        target_user.user_id == EventModel.event_creator_id,
                    ),
                ),
            )
            .where(
                ReportModel.report_id == report_id,
                ReportModel.deleted_at.is_(None),
            )
        ).one_or_none()
        if row is None:
            return None

        model, creator, target = row
        if target is None:
            return None

        target_event_count = self._count_target_events(target.user_id)
        previous_archived, previous_resolved = self._count_previous_reports(
            report_id=model.report_id,
            target_user_id=target.user_id,
        )

        resolved_by_name: str | None = None
        if model.resolved_by_id is not None:
            resolved_by_name = self.db.execute(
                select(UserModel.name).where(UserModel.user_id == model.resolved_by_id)
            ).scalar_one_or_none()

        return self._to_entity(
            model=model,
            creator=creator,
            target=target,
            target_event_count=target_event_count,
            previous_archived=previous_archived,
            previous_resolved=previous_resolved,
            resolved_by_name=resolved_by_name,
        )

    def _count_target_events(self, target_user_id: UUID) -> int:
        return int(
            self.db.execute(
                select(func.count())
                .select_from(EventModel)
                .where(
                    EventModel.event_creator_id == target_user_id,
                    EventModel.deleted_at.is_(None),
                )
            ).scalar_one()
        )

    def _count_previous_reports(
        self, report_id: UUID, target_user_id: UUID
    ) -> tuple[int, int]:
        is_archived = ReportModel.status == ReportStatusEnum.REJECTED
        is_resolved = ReportModel.status == ReportStatusEnum.RESOLVED

        archived_count, resolved_count = self.db.execute(
            select(
                func.count().filter(is_archived),
                func.count().filter(is_resolved),
            )
            .select_from(ReportModel)
            .outerjoin(EventModel, EventModel.event_id == ReportModel.reported_event_id)
            .where(
                ReportModel.deleted_at.is_(None),
                ReportModel.report_id != report_id,
                or_(
                    ReportModel.reported_user_id == target_user_id,
                    EventModel.event_creator_id == target_user_id,
                ),
            )
        ).one()
        return int(archived_count), int(resolved_count)

    @staticmethod
    def _to_entity(
        model: ReportModel,
        creator: UserModel,
        target: UserModel,
        target_event_count: int,
        previous_archived: int,
        previous_resolved: int,
        resolved_by_name: str | None,
    ) -> AdminReportDetailRecord:
        opened_at = _as_utc(model.created_at)
        # ReportModel has no separate reported_at column, so opened_at and
        # reported_at share the same timestamp unless reported_at is defined
        # on the model.
        raw_reported_at = getattr(model, "reported_at", None)
        reported_at = (
            (
                raw_reported_at
                if raw_reported_at.tzinfo is not None
                else raw_reported_at.replace(tzinfo=UTC)
            )
            if raw_reported_at is not None
            else opened_at
        )
        target_created_at = (
            target.created_at
            if target.created_at.tzinfo is not None
            else target.created_at.replace(tzinfo=UTC)
        )
        return AdminReportDetailRecord(
            report_id=model.report_id,
            report_number=model.report_number,
            status=model.status,
            opened_at=opened_at,
            reported_at=reported_at,
            reason=model.report_type,
            description=model.description,
            reported_event_id=model.reported_event_id,
            target_user_id=target.user_id,
            target_user_name=target.name,
            target_user_type=target.user_type,
            target_created_at=target_created_at,
            target_banned_at=target.banned_at,
            target_suspended_until=target.suspended_until,
            target_event_count=target_event_count,
            reported_by_id=creator.user_id,
            reported_by_name=creator.name,
            previous_archived_count=previous_archived,
            previous_resolved_count=previous_resolved,
            resolved_by_id=model.resolved_by_id,
            resolved_by_name=resolved_by_name,
            resolved_at=model.resolved_at,
            resolution_action=model.resolution_action,
        )
