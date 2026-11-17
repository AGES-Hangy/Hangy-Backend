__all__ = [
    "OPEN_REPORT_STATUSES",
    "REPORT_TYPE_SCOPE",
    "ReportScopeEnum",
    "ReportTargetEnum",
    "ReportUnavailableReasonEnum",
]

from enum import StrEnum

from app.domain.enums.enums import ReportStatusEnum, ReportTypeEnum


class ReportTargetEnum(StrEnum):
    USER = "USER"
    EVENT = "EVENT"


class ReportScopeEnum(StrEnum):
    """What a report reason is about.

    CONTENT: what is public on the target (name, cover, description).
    EXPERIENCE: what happens at an event, so only its participants know.
    """

    CONTENT = "CONTENT"
    EXPERIENCE = "EXPERIENCE"


class ReportUnavailableReasonEnum(StrEnum):
    ALREADY_REPORTED = "ALREADY_REPORTED"
    PARTICIPANTS_ONLY = "PARTICIPANTS_ONLY"


# Domain constant (not a column). Only events use it to restrict who may report:
# a profile report is always CONTENT, whatever the reason.
REPORT_TYPE_SCOPE: dict[ReportTypeEnum, ReportScopeEnum] = {
    ReportTypeEnum.INAPPROPRIATE_CONTENT: ReportScopeEnum.CONTENT,
    ReportTypeEnum.HATE_SPEECH: ReportScopeEnum.CONTENT,
    ReportTypeEnum.SPAM: ReportScopeEnum.CONTENT,
    ReportTypeEnum.OTHER: ReportScopeEnum.CONTENT,
    ReportTypeEnum.FAKE_PROFILE: ReportScopeEnum.CONTENT,
    # "Evento enganoso" is about what happened (it did not match the
    # announcement), so it is EXPERIENCE. Validated with the PO on 2026-11-04.
    ReportTypeEnum.MISLEADING_EVENT: ReportScopeEnum.EXPERIENCE,
    ReportTypeEnum.HARASSMENT: ReportScopeEnum.EXPERIENCE,
    ReportTypeEnum.SAFETY_CONCERN: ReportScopeEnum.EXPERIENCE,
}

# A report counts against the one-open-report-per-reason limit while it is in
# one of these statuses; RESOLVED and REJECTED free the reason again.
OPEN_REPORT_STATUSES = (ReportStatusEnum.PENDING, ReportStatusEnum.REVIEWED)
