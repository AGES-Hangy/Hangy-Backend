import httpx

from app.infrastructure.push.expo_push_sender import (
    EXPO_PUSH_URL,
    ExpoPushSender,
)


def test_send_posts_a_message_per_token_and_returns_empty_when_all_delivered() -> None:
    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        messages = request.content
        assert request.url == EXPO_PUSH_URL
        assert messages
        return httpx.Response(
            200,
            json={"data": [{"status": "ok"}, {"status": "ok"}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = ExpoPushSender(client=client)

    rejected = sender.send(
        tokens=["ExponentPushToken[a]", "ExponentPushToken[b]"],
        title="Título",
        body="Corpo",
        data={"type": "CONNECTION_ACCEPTED"},
    )

    assert rejected == []
    assert len(captured_requests) == 1


def test_send_collects_tokens_rejected_as_device_not_registered() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"status": "ok"},
                    {
                        "status": "error",
                        "message": "not registered",
                        "details": {"error": "DeviceNotRegistered"},
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = ExpoPushSender(client=client)

    rejected = sender.send(
        tokens=["ExponentPushToken[valid]", "ExponentPushToken[stale]"],
        title="Título",
        body="Corpo",
        data={"type": "CONNECTION_ACCEPTED"},
    )

    assert rejected == ["ExponentPushToken[stale]"]


def test_send_includes_bearer_token_when_configured() -> None:
    captured_headers: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.append(request.headers)
        return httpx.Response(200, json={"data": [{"status": "ok"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = ExpoPushSender(access_token="expo-token", client=client)

    sender.send(
        tokens=["ExponentPushToken[a]"],
        title="Título",
        body="Corpo",
        data={},
    )

    assert captured_headers[0]["authorization"] == "Bearer expo-token"


def test_send_with_no_tokens_does_not_call_expo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Expo should not be called with no tokens")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = ExpoPushSender(client=client)

    assert sender.send(tokens=[], title="t", body="b", data={}) == []
