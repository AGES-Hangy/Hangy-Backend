from app.domain.entities import Event
from app.presentation.dtos import CancelEventOutput


class EventAssembler:
    @staticmethod
    def to_cancel_dto(event: Event) -> CancelEventOutput:
        if event.event_id is None:
            raise ValueError("A persisted event must have an id")
        return CancelEventOutput(
            event_id=event.event_id,
            status=event.event_status,
            updated_at=event.updated_at,
        )
