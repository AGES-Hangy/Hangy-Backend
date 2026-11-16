from app.domain.entities import AdminEventDetail
from app.presentation.dtos.admin_events import (
    AdminEventDetailOutput,
    AdminEventMetricsOutput,
    AdminEventOrganizerOutput,
)

__all__ = ["AdminEventsAssembler"]


class AdminEventsAssembler:
    @staticmethod
    def to_detail_dto(detail: AdminEventDetail) -> AdminEventDetailOutput:
        organizer = detail.organizer
        metrics = detail.metrics
        return AdminEventDetailOutput(
            event_id=detail.event_id,
            title=detail.title,
            description=detail.description,
            event_date=detail.starts_at,
            end_date=detail.ends_at,
            location_name=detail.location_name,
            location_neighborhood=detail.location_neighborhood,
            location_city=detail.location_city,
            latitude=detail.latitude,
            longitude=detail.longitude,
            privacy=detail.privacy,
            status=detail.status,
            moderation_status=detail.moderation_status,
            removed_at=detail.removed_at,
            cover_photo_url=detail.cover_photo_url,
            max_participants=detail.max_participants,
            created_at=detail.created_at,
            tags=list(detail.tags),
            organizer=AdminEventOrganizerOutput(
                user_id=organizer.user_id,
                name=organizer.name,
                photo_url=organizer.photo_url,
                moderation_status=organizer.moderation_status,
                event_count=organizer.event_count,
                report_count=organizer.report_count,
            ),
            metrics=AdminEventMetricsOutput(
                participant_count=metrics.participant_count,
                pending_count=metrics.pending_count,
                report_count=metrics.report_count,
                report_upheld_count=metrics.report_upheld_count,
            ),
        )
