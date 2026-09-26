from app.domain.entities import BusinessRegistration, PersonRegistration
from app.presentation.dtos import RegisterBusinessRequest, RegisterPersonalRequest


class UserMapper:
    @staticmethod
    def to_registration(
        dto: RegisterPersonalRequest | RegisterBusinessRequest,
    ) -> PersonRegistration | BusinessRegistration:
        if isinstance(dto, RegisterPersonalRequest):
            return PersonRegistration(
                email=dto.email,
                password=dto.password.get_secret_value(),
                name=dto.name,
                cpf=dto.cpf,
                phone=dto.phone,
                date_of_birth=dto.date_of_birth,
                country=dto.country,
                state=dto.state,
                city=dto.city,
                accepted_terms_version=dto.accepted_terms_version,
            )
        return BusinessRegistration(
            email=dto.email,
            password=dto.password.get_secret_value(),
            business_name=dto.business_name,
            cnpj=dto.cnpj,
            phone=dto.phone,
            description=dto.description,
            address=dto.address,
            latitude=dto.location.latitude,
            longitude=dto.location.longitude,
            accepted_terms_version=dto.accepted_terms_version,
        )
