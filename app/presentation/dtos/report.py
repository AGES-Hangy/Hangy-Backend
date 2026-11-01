from pydantic import BaseModel

from app.domain.enums import ReportTypeEnum


class ReportReasonOutput(BaseModel):
    """A report reason as returned to API clients."""

    code: ReportTypeEnum
    label: str