from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.entities import Report
from app.domain.enums import ReportResolutionActionEnum, ReportStatusEnum
from app.infrastructure.repository.models.report_model import ReportModel


class SqlAlchemyReportRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, report_id: UUID) -> Report | None:
        model = self.db.scalar(
            select(ReportModel).where(
                ReportModel.report_id == report_id,
                ReportModel.deleted_at.is_(None),
            )
        )
        return self._to_entity(model) if model is not None else None

    def resolve(
        self,
        report_id: UUID,
        *,
        resolved_by_id: UUID,
        resolved_at: datetime,
        resolution_action: ReportResolutionActionEnum,
    ) -> None:
        """Mark the report RESOLVED.

        Flush only: the caller commits (see
        SqlAlchemyUserRepository.set_moderation).
        """
        model = self.db.scalar(
            select(ReportModel).where(ReportModel.report_id == report_id)
        )
        if model is None:
            raise ValueError("A resolved report must already exist")
        model.status = ReportStatusEnum.RESOLVED
        model.resolved_by_id = resolved_by_id
        model.resolved_at = resolved_at
        model.resolution_action = resolution_action
        self.db.flush()

    def resolve_open_for_event(
        self,
        event_id: UUID,
        *,
        resolved_by_id: UUID,
        resolved_at: datetime,
        resolution_action: ReportResolutionActionEnum,
    ) -> int:
        """Mark every PENDING/REVIEWED report about the event as RESOLVED.

        Flush only: the caller commits. Returns how many reports were closed.
        """
        result = self.db.execute(
            update(ReportModel)
            .where(
                ReportModel.reported_event_id == event_id,
                ReportModel.deleted_at.is_(None),
                ReportModel.status.in_(
                    (ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED)
                ),
            )
            .values(
                status=ReportStatusEnum.RESOLVED,
                resolved_by_id=resolved_by_id,
                resolved_at=resolved_at,
                resolution_action=resolution_action,
            )
        )
        self.db.flush()
        return result.rowcount

    @staticmethod
    def _to_entity(model: ReportModel) -> Report:
        return Report(
            report_id=model.report_id,
            report_creator_id=model.report_creator_id,
            report_type=model.report_type,
            description=model.description,
            updated_at=model.updated_at,
            status=model.status,
            reported_user_id=model.reported_user_id,
            reported_event_id=model.reported_event_id,
            deleted_at=model.deleted_at,
            resolved_by_id=model.resolved_by_id,
            resolved_at=model.resolved_at,
            resolution_action=model.resolution_action,
        )
