from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.domain.assemblers import TermsAssembler
from app.domain.services import GetTerms, NoTermsPublishedError
from app.presentation.dtos import TermsVersionOutput

router = APIRouter(tags=["Terms"])


@router.get(
    "/terms/current",
    response_model=TermsVersionOutput,
    status_code=status.HTTP_200_OK,
    summary="Obter versão vigente dos termos de uso",
    description="Retorna a versão atual dos termos de uso e política de privacidade.",
)
def get_current_terms() -> TermsVersionOutput:
    service = GetTerms(
        version=settings.terms_version,
        published_at=settings.terms_published_at,
        url=settings.terms_url,
        summary=settings.terms_summary,
    )
    try:
        terms = service.execute()
    except NoTermsPublishedError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No terms version published",
        ) from error
    return TermsAssembler.to_dto(terms)
