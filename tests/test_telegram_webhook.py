import httpx
import pytest

from vimi_social.telegram.app import build_telegram_app
from vimi_social.telegram.models import TelegramUpdate


class FakeTelegramService:
    def __init__(self) -> None:
        self.update_ids: list[int] = []

    async def handle_update(self, update: TelegramUpdate) -> None:
        self.update_ids.append(update.update_id)

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_webhook_rejects_requests_without_telegram_secret() -> None:
    service = FakeTelegramService()
    app = build_telegram_app(service, "test-secret")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/telegram/webhook", json={"update_id": 1})

    assert response.status_code == 401
    assert service.update_ids == []


@pytest.mark.asyncio
async def test_webhook_accepts_verified_telegram_update() -> None:
    service = FakeTelegramService()
    app = build_telegram_app(service, "test-secret")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/telegram/webhook",
            json={"update_id": 42},
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert service.update_ids == [42]
