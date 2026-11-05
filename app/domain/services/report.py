__all__ = [
    "ExactlyOneReportTargetError",
    "InvalidReportReasonError",
    "ReportAlreadyUnderReviewError",
    "ReportEventVisibility",
    "ReportReasonsService",
    "ReportRepository",
    "ReportService",
    "ReportTargetNotFoundError",
]

from typing import Protocol
from uuid import UUID

from app.domain.entities import EventDetails, NewReport, Report, ReportReason
from app.domain.enums import ReportTargetEnum, ReportTypeEnum
from app.domain.services.auth import UserRepository
from app.domain.services.event_details import (
    EventCancelledError,
    EventDetailsNotFoundError,
)

# Motivos exibidos na tela de denuncia, por tipo de alvo (ordem = ordem da lista).
# Estabelecimento e um USER, entao usa a lista de USER.
_REASONS_BY_TARGET: dict[ReportTargetEnum, tuple[ReportReason, ...]] = {
    ReportTargetEnum.USER: (
        ReportReason(ReportTypeEnum.HARASSMENT, "Assédio ou intimidação"),
        ReportReason(ReportTypeEnum.SPAM, "Spam ou golpe"),
        ReportReason(ReportTypeEnum.HATE_SPEECH, "Discurso de ódio"),
        ReportReason(ReportTypeEnum.FAKE_PROFILE, "Perfil falso"),
        ReportReason(ReportTypeEnum.INAPPROPRIATE_CONTENT, "Conteúdo inapropriado"),
        ReportReason(ReportTypeEnum.SAFETY_CONCERN, "Violação de segurança"),
        ReportReason(ReportTypeEnum.OTHER, "Outro"),
    ),
    ReportTargetEnum.EVENT: (
        ReportReason(ReportTypeEnum.SPAM, "Spam ou golpe"),
        ReportReason(ReportTypeEnum.INAPPROPRIATE_CONTENT, "Conteúdo inapropriado"),
        ReportReason(ReportTypeEnum.HATE_SPEECH, "Discurso de ódio"),
        ReportReason(ReportTypeEnum.SAFETY_CONCERN, "Violação de segurança"),
        ReportReason(ReportTypeEnum.OTHER, "Outro"),
    ),
}


class ReportReasonsService:
    """List the report reasons available for a given kind of target."""

    def get_reasons(self, target: ReportTargetEnum) -> list[ReportReason]:
        return list(_REASONS_BY_TARGET[target])


class ReportRepository(Protocol):
    def create(self, new_report: NewReport) -> Report: ...


class ReportEventVisibility(Protocol):
    """What GET /events/{event_id} answers, so both share one visibility rule."""

    def get_details(self, event_id: UUID, viewer_id: UUID) -> EventDetails: ...


class ExactlyOneReportTargetError(Exception):
    """Raised when a report names both a user and an event, or neither."""


class InvalidReportReasonError(Exception):
    """Raised when the report reason is not one of the known report types."""


class ReportTargetNotFoundError(Exception):
    """Raised when the reported user or event does not exist for the author."""


class ReportAlreadyUnderReviewError(Exception):
    """Raised when the author already has a PENDING report for the same target."""


class ReportService:
    def __init__(
        self,
        repository: ReportRepository,
        user_repository: UserRepository,
        event_visibility: ReportEventVisibility,
    ) -> None:
        self.repository = repository
        self.user_repository = user_repository
        self.event_visibility = event_visibility

    def create_report(self, new_report: NewReport) -> Report:
        if (new_report.reported_user_id is None) == (
            new_report.reported_event_id is None
        ):
            raise ExactlyOneReportTargetError

        if new_report.reported_user_id is not None:
            target = self.user_repository.get_by_id(new_report.reported_user_id)
            if target is None or target.deleted_at is not None:
                raise ReportTargetNotFoundError
        elif new_report.reported_event_id is not None:
            try:
                self.event_visibility.get_details(
                    new_report.reported_event_id, new_report.report_creator_id
                )
            except (EventDetailsNotFoundError, EventCancelledError) as error:
                raise ReportTargetNotFoundError from error

        return self.repository.create(new_report)
