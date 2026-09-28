from typing import Protocol


class PushSender(Protocol):
    def send(
        self, tokens: list[str], title: str, body: str, data: dict[str, str]
    ) -> list[str]:
        """Send a push message to each token, returning the tokens Expo rejected
        as DeviceNotRegistered, so callers can clean them up."""
        ...


class NullPushSender:
    """No-op sender used when no PushSender is configured."""

    def send(
        self, tokens: list[str], title: str, body: str, data: dict[str, str]
    ) -> list[str]:
        return []
