from app.domain.entities import BusinessRegistration, PersonRegistration, User
from app.domain.services.register_business import RegisterBusinessService
from app.domain.services.register_personal import RegisterPersonalService


class OutdatedTermsVersionError(Exception):
    """Raised when the client accepted a terms version other than the current one."""


class RegisterService:
    def __init__(
        self,
        personal_service: RegisterPersonalService,
        business_service: RegisterBusinessService,
        current_terms_version: str | None = None,
    ) -> None:
        self.personal_service = personal_service
        self.business_service = business_service
        self.current_terms_version = current_terms_version

    def register(self, registration: PersonRegistration | BusinessRegistration) -> User:
        # The account records which terms it accepted, so it must be the
        # version currently published (GET /terms/current), not any string.
        if (
            self.current_terms_version is not None
            and registration.accepted_terms_version != self.current_terms_version
        ):
            raise OutdatedTermsVersionError
        if isinstance(registration, PersonRegistration):
            return self.personal_service.register(registration)
        return self.business_service.register(registration)
