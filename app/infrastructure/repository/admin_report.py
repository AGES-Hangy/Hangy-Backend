__all__ = ["SqlAlchemyAdminReportsRepository"]

from datetime import UTC
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.domain.entities import AdminReportDetailRecord
from app.domain.enums import ReportStatusEnum
from app.infrastructure.repository.models import UserModel
from app.infrastructure.repository.models.event_model import EventModel
from app.infrastructure.repository.models.report_model import ReportModel


class SqlAlchemyAdminReportsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

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

        report_number = self._get_report_number(model)
        target_event_count = self._count_target_events(target.user_id)
        previous_archived, previous_resolved = self._count_previous_reports(
            report_id=model.report_id,
            target_user_id=target.user_id,
        )

        resolved_by_id = getattr(model, "resolved_by_id", None)
        resolved_by_name: str | None = None
        if resolved_by_id is not None:
            resolved_by_name = self.db.execute(
                select(UserModel.name).where(UserModel.user_id == resolved_by_id)
            ).scalar_one_or_none()

        return self._to_entity(
            model=model,
            creator=creator,
            target=target,
            report_number=report_number,
            target_event_count=target_event_count,
            previous_archived=previous_archived,
            previous_resolved=previous_resolved,
            resolved_by_name=resolved_by_name,
        )

    def _get_report_number(self, model: ReportModel) -> int:
        explicit_number = getattr(model, "report_number", None)
        if explicit_number is not None:
            return int(explicit_number)

        timestamp_col = getattr(ReportModel, "created_at", ReportModel.updated_at)
        model_timestamp = getattr(model, "created_at", None) or model.updated_at
        return int(
            self.db.execute(
                select(func.count())
                .select_from(ReportModel)
                .where(
                    ReportModel.deleted_at.is_(None),
                    or_(
                        timestamp_col < model_timestamp,
                        and_(
                            timestamp_col == model_timestamp,
                            ReportModel.report_id <= model.report_id,
                        ),
                    ),
                )
            ).scalar_one()
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
        report_number: int,
        target_event_count: int,
        previous_archived: int,
        previous_resolved: int,
        resolved_by_name: str | None,
    ) -> AdminReportDetailRecord:
        raw_opened_at = getattr(model, "created_at", None) or model.updated_at
        opened_at = (
            raw_opened_at
            if raw_opened_at.tzinfo is not None
            else raw_opened_at.replace(tzinfo=UTC)
        )
        target_created_at = (
            target.created_at
            if target.created_at.tzinfo is not None
            else target.created_at.replace(tzinfo=UTC)
        )
        return AdminReportDetailRecord(
            report_id=model.report_id,
            report_number=report_number,
            status=model.status,
            opened_at=opened_at,
            reported_at=opened_at,
            reason=model.report_type,
            description=model.description,
            reported_event_id=model.reported_event_id,
            target_user_id=target.user_id,
            target_user_name=target.name,
            target_user_type=target.user_type,
            target_created_at=target_created_at,
            target_banned_at=getattr(target, "banned_at", None),
            target_suspended_until=getattr(target, "suspended_until", None),
            target_event_count=target_event_count,
            reported_by_id=creator.user_id,
            reported_by_name=creator.name,
            previous_archived_count=previous_archived,
            previous_resolved_count=previous_resolved,
            resolved_by_id=getattr(model, "resolved_by_id", None),
            resolved_by_name=resolved_by_name,
            resolved_at=getattr(model, "resolved_at", None),
            resolution_action=getattr(model, "resolution_action", None),
        )
