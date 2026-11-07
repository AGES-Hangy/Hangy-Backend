from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import NewReport, Report
from app.domain.enums import ReportResolutionActionEnum, ReportStatusEnum
from app.domain.services.report import ReportAlreadyUnderReviewError
from app.infrastructure.repository.models.report_model import ReportModel

PENDING_UNIQUE_INDEXES = ("uq_report_pending_user", "uq_report_pending_event")


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
            if self._is_pending_uniqueness_violation(error):
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

    @staticmethod
    def _is_pending_uniqueness_violation(error: IntegrityError) -> bool:
        """Tell the open-report unique indexes apart from any other violation.

        PostgreSQL names the violated index in the message. SQLite (tests) only
        lists the columns, so the author column of the index is used instead:
        report_number and the primary key do not contain it.
        """
        message = str(error.orig)
        if any(name in message for name in PENDING_UNIQUE_INDEXES):
            return True
        return "UNIQUE constraint failed: report.report_creator_id" in message

    @staticmethod
    def _to_entity(model: ReportModel) -> Report:
        return Report(
            report_id=model.report_id,
            report_creator_id=model.report_creator_id,
            report_type=model.report_type,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
            status=model.status,
            reported_user_id=model.reported_user_id,
            reported_event_id=model.reported_event_id,
            deleted_at=model.deleted_at,
            resolved_by_id=model.resolved_by_id,
            resolved_at=model.resolved_at,
            resolution_action=model.resolution_action,
        )