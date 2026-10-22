import httpx
import pytest

from scripts.configure_telegram_webhook import _telegram_request


def test_telegram_http_status_failure_does_not_expose_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:super-secret-staging-token"

    def fake_request(
        method: str,
        url: str,
        **_: object,
    ) -> httpx.Response:
        assert method == "POST"
        assert token in url
        return httpx.Response(401)

    monkeypatch.setattr(httpx, "request", fake_request)

    with pytest.raises(RuntimeError) as captured:
        _telegram_request("POST", token, "setWebhook")

    assert str(captured.value) == "Telegram setWebhook failed with HTTP 401"
    assert token not in str(captured.value)


def test_telegram_network_failure_suppresses_token_bearing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:super-secret-staging-token"

    def fake_request(
        method: str,
        url: str,
        **_: object,
    ) -> httpx.Response:
        request = httpx.Request(method, url)
        raise httpx.ConnectError("connection failed", request=request)

    monkeypatch.setattr(httpx, "request", fake_request)

    with pytest.raises(RuntimeError) as captured:
        _telegram_request("GET", token, "getWebhookInfo")

    assert str(captured.value) == "Telegram getWebhookInfo request failed"
    assert token not in str(captured.value)
    assert captured.value.__suppress_context__ is True
