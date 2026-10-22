import asyncio

from sqlalchemy.orm import Session, sessionmaker
from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.source.activities import ScoutActivities
from vimi_social.source.connectors import SourceConnectorRegistry
from vimi_social.source.x_connector import XSourceConnector
from vimi_social.telegram.client import TelegramBotApiClient
from vimi_social.telegram.outgoing import TelegramMessenger, TelegramOutgoingStore
from vimi_social.workflows.publication import PublicationWorkflow
from vimi_social.workflows.scout import ScoutWorkflow


async def run() -> None:
    settings = get_settings()
    client = await Client.connect(
        settings.temporal_target,
        namespace=settings.temporal_namespace,
    )
    engine = build_engine()
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )

    registry = SourceConnectorRegistry()
    x_connector: XSourceConnector | None = None
    if settings.x_bearer_token:
        x_connector = XSourceConnector(settings.x_bearer_token)
        registry.register(x_connector)

    messenger: TelegramMessenger | None = None
    if settings.telegram_bot_token:
        messenger = TelegramMessenger(
            TelegramOutgoingStore(session_factory),
            TelegramBotApiClient(settings.telegram_bot_token),
        )

    activities = ScoutActivities(session_factory, registry, messenger)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[PublicationWorkflow, ScoutWorkflow],
        activities=[
            activities.execute_scout_task,
            activities.deliver_scout_results,
        ],
    )
    try:
        await worker.run()
    finally:
        if x_connector is not None:
            await x_connector.aclose()
        if messenger is not None:
            await messenger.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
