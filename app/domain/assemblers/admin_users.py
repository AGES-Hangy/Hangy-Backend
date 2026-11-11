from typing import Literal

from app.domain.entities import AdminUserDetail, AdminUsersPage
from app.domain.enums import AuditActionEnum
from app.presentation.dtos.admin_users import (
    AdminModerationActorOutput,
    AdminModerationEntryOutput,
    AdminUserDetailOutput,
    AdminUserMetricsOutput,
    AdminUserOutput,
    AdminUsersOutput,
)

MODERATION_ACTION_NAMES: dict[
    AuditActionEnum, Literal["BANNED", "SUSPENDED", "REVERTED"]
] = {
    AuditActionEnum.USER_BANNED: "BANNED",
    AuditActionEnum.USER_SUSPENDED: "SUSPENDED",
    AuditActionEnum.USER_REVERTED: "REVERTED",
}


class AdminUsersAssembler:
    @staticmethod
    def to_dto(page: AdminUsersPage) -> AdminUsersOutput:
        return AdminUsersOutput(
            items=[
                AdminUserOutput(
                    user_id=item.user_id,
                    name=item.name,
                    moderation_status=item.moderation_status,
                    suspended_until=item.suspended_until,
                    event_count=item.event_count,
                    report_count=item.report_count,
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor,
        )

    @staticmethod
    def to_detail_dto(detail: AdminUserDetail) -> AdminUserDetailOutput:
        return AdminUserDetailOutput(
            user_id=detail.user_id,
            name=detail.name,
            email=detail.email,
            member_since=detail.member_since,
            moderation_status=detail.moderation_status,
            banned_at=detail.banned_at,
            suspended_until=detail.suspended_until,
            metrics=AdminUserMetricsOutput(
                event_count=detail.metrics.event_count,
                event_cancelled_count=detail.metrics.event_cancelled_count,
                report_count=detail.metrics.report_count,
                report_upheld_count=detail.metrics.report_upheld_count,
            ),
            moderation_history=[
                AdminModerationEntryOutput(
                    action=MODERATION_ACTION_NAMES[entry.action],
                    actor=(
                        AdminModerationActorOutput(
                            id=entry.actor.user_id, name=entry.actor.name
                        )
                        if entry.actor is not None
                        else None
                    ),
                    occurred_at=entry.occurred_at,
                    report_id=entry.report_id,
                )
                for entry in detail.moderation_history
            ],
        )