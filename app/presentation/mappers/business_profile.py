from app.domain.entities import BusinessProfileLocation, BusinessProfileUpdate
from app.presentation.dtos import BusinessProfileUpdateInput

__all__ = ["BusinessProfileMapper"]


class BusinessProfileMapper:
    @staticmethod
    def to_update(dto: BusinessProfileUpdateInput) -> BusinessProfileUpdate:
        data = dto.model_dump(exclude_unset=True)
        data.pop("cnpj", None)
        if "location" in data:
            location_val = data["location"]
            if location_val is not None:
                data["location"] = BusinessProfileLocation(
                    latitude=location_val["latitude"],
                    longitude=location_val["longitude"],
                )
        return BusinessProfileUpdate(**data)
