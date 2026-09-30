from app.domain.entities import TermsVersion


class NoTermsPublishedError(Exception):
    """Raised when no terms version is configured."""


class GetTerms:
    """Return the currently published terms version."""

    def __init__(self, version: str, published_at: str, url: str, summary: str) -> None:
        self._version = version
        self._published_at = published_at
        self._url = url
        self._summary = summary

    def execute(self) -> TermsVersion:
        if not self._version:
            raise NoTermsPublishedError
        return TermsVersion(
            version=self._version,
            published_at=self._published_at,
            url=self._url,
            summary=self._summary,
        )
