from app.domain.entities import ReportReason
from app.domain.enums import ReportTargetEnum, ReportTypeEnum

# Motivos exibidos na tela de denuncia, por tipo de alvo (ordem = ordem da lista).
# Estabelecimento e um USER, entao usa a lista de USER.
_REASONS_BY_TARGET: dict[ReportTargetEnum, tuple[ReportReason, ...]] = {
    ReportTargetEnum.USER: (
        ReportReason(ReportTypeEnum.HARASSMENT, "Abuso"),
        ReportReason(ReportTypeEnum.INAPPROPRIATE_CONTENT, "Conteúdo inapropriado"),
        ReportReason(ReportTypeEnum.FAKE_PROFILE, "Perfil fake"),
        ReportReason(ReportTypeEnum.HATE_SPEECH, "Discurso de ódio"),
        ReportReason(ReportTypeEnum.SAFETY_CONCERN, "Violação de segurança"),
        ReportReason(ReportTypeEnum.OTHER, "Outro"),
    ),
    ReportTargetEnum.EVENT: (
        ReportReason(ReportTypeEnum.HARASSMENT, "Abuso"),
        ReportReason(ReportTypeEnum.INAPPROPRIATE_CONTENT, "Conteúdo inapropriado"),
        ReportReason(ReportTypeEnum.HATE_SPEECH, "Discurso de ódio"),
        ReportReason(ReportTypeEnum.SPAM, "Propaganda enganosa"),
        ReportReason(ReportTypeEnum.SAFETY_CONCERN, "Violação de segurança"),
        ReportReason(ReportTypeEnum.OTHER, "Outro"),
    ),
}


class ReportReasonsService:
    """List the report reasons available for a given kind of target."""

    def get_reasons(self, target: ReportTargetEnum) -> list[ReportReason]:
        return list(_REASONS_BY_TARGET[target])