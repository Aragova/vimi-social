from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.source.service import SourceTaskService
from vimi_social.source.temporal import TemporalScoutWorkflowStarter
from vimi_social.telegram.app import build_telegram_app
from vimi_social.telegram.client import TelegramBotApiClient
from vimi_social.telegram.identity import TelegramIdentityResolver, TelegramUpdateGuard
from vimi_social.telegram.outgoing import (
    TelegramMessenger,
    TelegramOutgoingStore,
)
from vimi_social.telegram.service import TelegramBotService


def create_application() -> FastAPI:
    settings = get_settings()
    if settings.telegram_bot_token is None:
        raise RuntimeError("VIMI_TELEGRAM_BOT_TOKEN is required for the bot process")
    if settings.telegram_webhook_secret is None:
        raise RuntimeError("VIMI_TELEGRAM_WEBHOOK_SECRET is required for the bot process")

    engine = build_engine()
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    identity_resolver = TelegramIdentityResolver(session_factory)
    update_guard = TelegramUpdateGuard(session_factory)
    outgoing_store = TelegramOutgoingStore(session_factory)
    gateway = TelegramBotApiClient(settings.telegram_bot_token)
    messenger = TelegramMessenger(outgoing_store, gateway)
    source_tasks = SourceTaskService(session_factory)
    scout_starter = TemporalScoutWorkflowStarter(
        settings.temporal_target,
        settings.temporal_namespace,
        settings.temporal_task_queue,
    )
    service = TelegramBotService(
        identity_resolver,
        update_guard,
        messenger,
        source_tasks,
        scout_starter,
    )
    return build_telegram_app(service, settings.telegram_webhook_secret)


app = create_application()
