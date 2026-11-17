__all__ = [
    "CannotReportYourselfError",
    "ExactlyOneReportTargetError",
    "ReportAlreadyUnderReviewError",
    "ReportEventVisibility",
    "ReportParticipantsOnlyError",
    "ReportReasonRequiresParticipationError",
    "ReportReasonsService",
    "ReportRepository",
    "ReportService",
    "ReportTargetAccess",
    "ReportTargetGuard",
    "ReportTargetNotFoundError",
]

from dataclasses import dataclass, replace
from typing import Protocol
from uuid import UUID

from app.domain.entities import EventDetails, NewReport, Report, ReportReason
from app.domain.enums import (
    REPORT_TYPE_SCOPE,
    EventParticipantStatusEnum,
    EventPrivacyEnum,
    ReportScopeEnum,
    ReportTargetEnum,
    ReportTypeEnum,
    ReportUnavailableReasonEnum,
)
from app.domain.services.auth import UserRepository
from app.domain.services.event_details import (
    EventCancelledError,
    EventDetailsNotFoundError,
    EventInviteOnlyError,
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
        ReportReason(ReportTypeEnum.MISLEADING_EVENT, "Evento enganoso"),
        ReportReason(ReportTypeEnum.HARASSMENT, "Assédio ou intimidação"),
        ReportReason(ReportTypeEnum.SAFETY_CONCERN, "Violação de segurança"),
        ReportReason(ReportTypeEnum.OTHER, "Outro"),
    ),
}


class ReportRepository(Protocol):
    def create(self, new_report: NewReport) -> Report: ...

    def list_open_report_types(
        self,
        creator_id: UUID,
        *,
        reported_user_id: UUID | None,
        reported_event_id: UUID | None,
    ) -> set[ReportTypeEnum]:
        """Reasons the author still has an open (PENDING/REVIEWED) report for."""
        ...


class ReportEventVisibility(Protocol):
    """What GET /events/{event_id} answers, so both share one visibility rule."""

    def get_details(self, event_id: UUID, viewer_id: UUID) -> EventDetails: ...


class ExactlyOneReportTargetError(Exception):
    """Raised when a report names both a user and an event, or neither."""


class ReportTargetNotFoundError(Exception):
    """Raised when the reported user or event does not exist for the author."""


class CannotReportYourselfError(Exception):
    """Raised when the author reports their own profile or their own event."""


class ReportParticipantsOnlyError(Exception):
    """Raised when a PRIVATE or INVITE_ONLY event is reported by a non-participant."""


class ReportReasonRequiresParticipationError(Exception):
    """Raised when an EXPERIENCE reason is used by a non-participant."""


class ReportAlreadyUnderReviewError(Exception):
    """Raised when the author already has an open report for target and reason."""


@dataclass(frozen=True, slots=True)
class ReportTargetAccess:
    """What the author may report on a target they are allowed to report at all."""

    can_report_experience: bool


def report_scope(target: ReportTargetEnum, report_type: ReportTypeEnum):
    """A profile report is always CONTENT; an event report follows the reason."""
    if target is ReportTargetEnum.USER:
        return ReportScopeEnum.CONTENT
    return REPORT_TYPE_SCOPE[report_type]


class ReportTargetGuard:
    """Who may report which target. Shared by the reasons list and the report."""

    def __init__(
        self,
        user_repository: UserRepository,
        event_visibility: ReportEventVisibility,
    ) -> None:
        self.user_repository = user_repository
        self.event_visibility = event_visibility

    def check(
        self,
        author_id: UUID,
        *,
        reported_user_id: UUID | None,
        reported_event_id: UUID | None,
    ) -> ReportTargetAccess:
        if reported_user_id is not None:
            return self._check_user(author_id, reported_user_id)
        assert reported_event_id is not None
        return self._check_event(author_id, reported_event_id)

    def _check_user(self, author_id: UUID, user_id: UUID) -> ReportTargetAccess:
        if user_id == author_id:
            raise CannotReportYourselfError
        target = self.user_repository.get_by_id(user_id)
        if target is None or target.deleted_at is not None:
            raise ReportTargetNotFoundError
        return ReportTargetAccess(can_report_experience=True)

    def _check_event(self, author_id: UUID, event_id: UUID) -> ReportTargetAccess:
        # The participation rule is the one GET /events/{id} already applies; it
        # is read from there instead of queried again.
        try:
            details = self.event_visibility.get_details(event_id, author_id)
        except EventInviteOnlyError as error:
            raise ReportParticipantsOnlyError from error
        except (EventDetailsNotFoundError, EventCancelledError) as error:
            raise ReportTargetNotFoundError from error

        if details.viewer.is_organizer:
            raise CannotReportYourselfError
        is_participant = (
            details.viewer.participation_status is EventParticipantStatusEnum.CONFIRMED
        )
        if details.event.event_privacy is not EventPrivacyEnum.PUBLIC and (
            not is_participant
        ):
            raise ReportParticipantsOnlyError
        return ReportTargetAccess(can_report_experience=is_participant)


class ReportReasonsService:
    """List the report reasons the author can use on one specific target."""

    def __init__(
        self,
        repository: ReportRepository,
        user_repository: UserRepository,
        event_visibility: ReportEventVisibility,
    ) -> None:
        self.repository = repository
        self.guard = ReportTargetGuard(user_repository, event_visibility)

    def get_reasons(
        self, author_id: UUID, target: ReportTargetEnum, target_id: UUID
    ) -> list[ReportReason]:
        reported_user_id = target_id if target is ReportTargetEnum.USER else None
        reported_event_id = target_id if target is ReportTargetEnum.EVENT else None
        access = self.guard.check(
            author_id,
            reported_user_id=reported_user_id,
            reported_event_id=reported_event_id,
        )
        open_types = self.repository.list_open_report_types(
            author_id,
            reported_user_id=reported_user_id,
            reported_event_id=reported_event_id,
        )

        reasons: list[ReportReason] = []
        for reason in _REASONS_BY_TARGET[target]:
            scope = report_scope(target, reason.code)
            unavailable_reason = None
            if scope is ReportScopeEnum.EXPERIENCE and not access.can_report_experience:
                unavailable_reason = ReportUnavailableReasonEnum.PARTICIPANTS_ONLY
            elif reason.code in open_types:
                unavailable_reason = ReportUnavailableReasonEnum.ALREADY_REPORTED
            reasons.append(
                replace(
                    reason,
                    scope=scope,
                    available=unavailable_reason is None,
                    unavailable_reason=unavailable_reason,
                )
            )
        return reasons


class ReportService:
    def __init__(
        self,
        repository: ReportRepository,
        user_repository: UserRepository,
        event_visibility: ReportEventVisibility,
    ) -> None:
        self.repository = repository
        self.guard = ReportTargetGuard(user_repository, event_visibility)

    def create_report(self, new_report: NewReport) -> Report:
        if (new_report.reported_user_id is None) == (
            new_report.reported_event_id is None
        ):
            raise ExactlyOneReportTargetError

        access = self.guard.check(
            new_report.report_creator_id,
            reported_user_id=new_report.reported_user_id,
            reported_event_id=new_report.reported_event_id,
        )
        target = (
            ReportTargetEnum.USER
            if new_report.reported_user_id is not None
            else ReportTargetEnum.EVENT
        )
        if (
            report_scope(target, new_report.report_type) is ReportScopeEnum.EXPERIENCE
            and not access.can_report_experience
        ):
            raise ReportReasonRequiresParticipationError

        # Same rule as the unique indexes, checked first only to answer a clear
        # 409; the indexes remain the guarantee against a concurrent request.
        open_types = self.repository.list_open_report_types(
            new_report.report_creator_id,
            reported_user_id=new_report.reported_user_id,
            reported_event_id=new_report.reported_event_id,
        )
        if new_report.report_type in open_types:
            raise ReportAlreadyUnderReviewError

        return self.repository.create(new_report)
