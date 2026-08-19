from dataclasses import dataclass

from app.domain.enums import TokenType


@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str
    token_type: TokenType = TokenType.BEARER
