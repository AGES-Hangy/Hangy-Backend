from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import NewReport, Report
from app.domain.enums import ReportResolutionActionEnum, ReportStatusEnum
from app.domain.services.report import ReportAlreadyUnderReviewError
from app.infrastructure.repository.models.report_model import ReportModel


class SqlAlchemyReportRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, new_report: NewReport) -> Report:
        model = ReportModel(
            report_creator_id=new_report.report_creator_id,
            reported_user_id=new_report.reported_user_id,
            reported_event_id=new_report.reported_event_id,
            report_type=new_report.report_type,
            description=new_report.description,
            status=ReportStatusEnum.PENDING,
        )
        self.db.add(model)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            if self._pending_exists(new_report):
                raise ReportAlreadyUnderReviewError from error
            raise
        self.db.refresh(model)
        return self._to_entity(model)

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

    def _pending_exists(self, new_report: NewReport) -> bool:
        # Mirrors the partial unique indexes, deleted_at included: a soft
        # deleted PENDING report still occupies the index.
        query = select(ReportModel.report_id).where(
            ReportModel.report_creator_id == new_report.report_creator_id,
            ReportModel.status == ReportStatusEnum.PENDING,
            ReportModel.reported_user_id == new_report.reported_user_id
            if new_report.reported_user_id is not None
            else ReportModel.reported_event_id == new_report.reported_event_id,
        )
        return self.db.scalar(query) is not None

    @staticmethod
    def _to_entity(model: ReportModel) -> Report:
        return Report(
            report_id=model.report_id,
            report_creator_id=model.report_creator_id,
            report_type=model.report_type,
            description=model.description,
            created_at=getattr(model, "created_at", None) or datetime.now(UTC),
            updated_at=model.updated_at,
            status=model.status,
            reported_user_id=model.reported_user_id,
            reported_event_id=model.reported_event_id,
            deleted_at=model.deleted_at,
            resolved_by_id=model.resolved_by_id,
            resolved_at=model.resolved_at,
            resolution_action=model.resolution_action,
        )
