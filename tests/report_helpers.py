from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import OPEN_REPORT_STATUSES, ReportTypeEnum
from app.infrastructure.repository.models import ReportModel


def free_report_type(
    db: Session,
    creator_id: UUID,
    *,
    reported_user_id: UUID | None,
    reported_event_id: UUID | None,
    preferred: ReportTypeEnum = ReportTypeEnum.HARASSMENT,
) -> ReportTypeEnum:
    """Pick a reason the author has no open report for on this target.

    Fixtures insert many reports straight into the database; the open-report
    unique index allows only one per author, target and reason.
    """
    taken = set(
        db.scalars(
            select(ReportModel.report_type).where(
                ReportModel.report_creator_id == creator_id,
                ReportModel.reported_user_id == reported_user_id,
                ReportModel.reported_event_id == reported_event_id,
                ReportModel.status.in_(OPEN_REPORT_STATUSES),
            )
        )
    )
    candidates = [preferred, *(t for t in ReportTypeEnum if t is not preferred)]
    return next(t for t in candidates if t not in taken)
