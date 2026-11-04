from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import NewReport, Report
from app.domain.enums import ReportStatusEnum
from app.domain.services.report import ReportAlreadyUnderReviewError
from app.infrastructure.repository.models import ReportModel


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

    def _pending_exists(self, new_report: NewReport) -> bool:
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
            created_at=model.created_at,
            updated_at=model.updated_at,
            status=model.status,
            reported_user_id=model.reported_user_id,
            reported_event_id=model.reported_event_id,
            deleted_at=model.deleted_at,
        )