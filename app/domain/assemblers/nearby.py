from app.domain.entities import NearbyEvent, NearbyEvents
from app.presentation.dtos import (
    EventLocationOutput,
    NearbyEventOutput,
    NearbyEventsOutput,
)


class NearbyEventAssembler:
    @staticmethod
    def to_dto(events: NearbyEvents) -> NearbyEventsOutput:
        return NearbyEventsOutput(
            items=[NearbyEventAssembler._item_to_dto(item) for item in events.items]
        )

    @staticmethod
    def _item_to_dto(event: NearbyEvent) -> NearbyEventOutput:
        return NearbyEventOutput(
            event_id=event.event_id,
            title=event.title,
            event_date=event.event_date,
            location=EventLocationOutput(
                latitude=event.latitude,
                longitude=event.longitude,
            ),
            location_name=event.location_name,
            location_precision=event.location_precision,
            location_radius_m=event.location_radius_m,
            privacy=event.privacy,
            cover_photo_url=event.cover_photo_url,
            distance_m=event.distance_m,
            participants_count=event.participants_count,
            is_confirmed=event.is_confirmed,
        )
