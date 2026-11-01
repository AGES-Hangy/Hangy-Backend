from app.domain.entities import ReportReason
from app.presentation.dtos import ReportReasonOutput


class ReportAssembler:
    """Build report response DTOs from domain entities."""

    @staticmethod
    def to_reason_dto(reason: ReportReason) -> ReportReasonOutput:
        return ReportReasonOutput(code=reason.code, label=reason.label)

    @staticmethod
    def to_reason_dtos(reasons: list[ReportReason]) -> list[ReportReasonOutput]:
        return [ReportAssembler.to_reason_dto(reason) for reason in reasons]