from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TermsVersionOutput:
    """Response returned to clients by the terms endpoint."""

    version: str
    published_at: str
    url: str
    summary: str
