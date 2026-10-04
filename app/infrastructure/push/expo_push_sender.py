import httpx

from app.config import settings

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_MAX_MESSAGES_PER_REQUEST = 100


class ExpoPushSender:
    """Sends push messages through Expo's push API."""

    def __init__(
        self,
        access_token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(timeout=10.0)
        self._access_token = access_token

    def send(
        self, tokens: list[str], title: str, body: str, data: dict[str, str]
    ) -> list[str]:
        if not tokens:
            return []

        headers = {"content-type": "application/json", "accept": "application/json"}
        if self._access_token:
            headers["authorization"] = f"Bearer {self._access_token}"

        rejected_tokens: list[str] = []
        for start in range(0, len(tokens), _MAX_MESSAGES_PER_REQUEST):
            chunk = tokens[start : start + _MAX_MESSAGES_PER_REQUEST]
            messages = [
                {"to": token, "title": title, "body": body, "data": data}
                for token in chunk
            ]
            response = self._client.post(EXPO_PUSH_URL, json=messages, headers=headers)
            response.raise_for_status()
            tickets = response.json().get("data", [])
            for token, ticket in zip(chunk, tickets, strict=False):
                if ticket.get("details", {}).get("error") == "DeviceNotRegistered":
                    rejected_tokens.append(token)

        return rejected_tokens


expo_push_sender = ExpoPushSender(access_token=settings.expo_access_token)
