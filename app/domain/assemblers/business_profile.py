from app.domain.entities import OwnBusinessProfile
from app.presentation.dtos import BusinessLocationOutput, BusinessMeOutput


class BusinessProfileAssembler:
    @staticmethod
    def to_dto(profile: OwnBusinessProfile) -> BusinessMeOutput:
        location = None
        if profile.latitude is not None and profile.longitude is not None:
            location = BusinessLocationOutput(
                latitude=profile.latitude, longitude=profile.longitude
            )
        return BusinessMeOutput(
            user_id=profile.user_id,
            business_name=profile.business_name,
            cnpj=profile.cnpj,
            description=profile.description,
            address=profile.address,
            location=location,
            phone=profile.phone,
        )