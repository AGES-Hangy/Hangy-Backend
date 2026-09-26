from app.domain.entities import BusinessRegistration, PersonRegistration, User
from app.domain.services.register_business import RegisterBusinessService
from app.domain.services.register_personal import RegisterPersonalService


class RegisterService:
    def __init__(
        self,
        personal_service: RegisterPersonalService,
        business_service: RegisterBusinessService,
    ) -> None:
        self.personal_service = personal_service
        self.business_service = business_service

    def register(self, registration: PersonRegistration | BusinessRegistration) -> User:
        if isinstance(registration, PersonRegistration):
            return self.personal_service.register(registration)
        return self.business_service.register(registration)
