from app.domain.entities import TermsVersion
from app.presentation.dtos import TermsVersionOutput


class TermsAssembler:
    """Build terms response DTOs from domain entities."""

    @staticmethod
    def to_dto(terms: TermsVersion) -> TermsVersionOutput:
        return TermsVersionOutput(
            version=terms.version,
            published_at=terms.published_at,
            url=terms.url,
            summary=terms.summary,
        )
