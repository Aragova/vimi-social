from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Response, status

from vimi_social.telegram.models import TelegramUpdate
from vimi_social.telegram.service import TelegramBotService, TelegramUpdateBusy


def build_telegram_app(service: TelegramBotService, webhook_secret: str) -> FastAPI:
    secret = webhook_secret.strip()
    if not secret:
        raise ValueError("telegram webhook secret must not be empty")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await service.aclose()

    app = FastAPI(title="ViMi Social Telegram", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/telegram/webhook")
    async def telegram_webhook(
        update: TelegramUpdate,
        webhook_header: Annotated[
            str | None,
            Header(alias="X-Telegram-Bot-Api-Secret-Token"),
        ] = None,
    ) -> dict[str, bool] | Response:
        if webhook_header is None or not compare_digest(webhook_header, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid telegram webhook secret",
            )

        try:
            await service.handle_update(update)
        except TelegramUpdateBusy:
            return Response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": "2"},
            )
        return {"ok": True}

    return app
