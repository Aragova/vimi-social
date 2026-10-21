from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Annotated, Protocol

from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.responses import JSONResponse

from vimi_social.telegram.models import TelegramUpdate
from vimi_social.telegram.service import TelegramUpdateBusy, TelegramUpdateRetryAfter


class TelegramUpdateHandler(Protocol):
    async def handle_update(self, update: TelegramUpdate) -> None: ...

    async def aclose(self) -> None: ...


def build_telegram_app(service: TelegramUpdateHandler, webhook_secret: str) -> FastAPI:
    secret = webhook_secret.strip()
    if not secret:
        raise ValueError("telegram webhook secret must not be empty")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        yield
        await service.aclose()

    app = FastAPI(title="ViMi Social Telegram", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/telegram/webhook", response_model=None)
    async def telegram_webhook(
        update: TelegramUpdate,
        webhook_header: Annotated[
            str | None,
            Header(alias="X-Telegram-Bot-Api-Secret-Token"),
        ] = None,
    ) -> Response:
        if webhook_header is None or not compare_digest(webhook_header, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid telegram webhook secret",
            )

        try:
            await service.handle_update(update)
        except TelegramUpdateRetryAfter as error:
            return Response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": str(error.retry_after_seconds)},
            )
        except TelegramUpdateBusy:
            return Response(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": "2"},
            )
        return JSONResponse({"ok": True})

    return app
