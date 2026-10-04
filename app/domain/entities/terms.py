from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TermsVersion:
    version: str
    published_at: str
    url: str
    summary: str
