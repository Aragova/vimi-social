import asyncio
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.media.delivery import MediaPreparationDeliveryActivities
from vimi_social.publication.delivery import PublicationDeliveryActivities
from vimi_social.publication.preview import PublicationPreviewActivities
from vimi_social.source.activities import ScoutActivities
from vimi_social.source.connectors import SourceConnectorRegistry
from vimi_social.source.query_planner import (
    MultilingualQueryPlanner,
    OpenAIEnglishIntentTranslator,
)
from vimi_social.source.x_connector import XSourceConnector
from vimi_social.telegram.client import TelegramBotApiClient
from vimi_social.telegram.outgoing import TelegramMessenger, TelegramOutgoingStore
from vimi_social.workflows.destination_publication import DestinationPublicationWorkflow
from vimi_social.workflows.media_preparation import MediaPreparationWorkflow
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

    translation_client: OpenAIEnglishIntentTranslator | None = None
    if settings.search_translation_api_key:
        translation_client = OpenAIEnglishIntentTranslator(
            settings.search_translation_api_key,
            model=settings.search_translation_model,
        )
    query_planner = MultilingualQueryPlanner(translation_client)

    messenger: TelegramMessenger | None = None
    if settings.telegram_bot_token:
        messenger = TelegramMessenger(
            TelegramOutgoingStore(session_factory),
            TelegramBotApiClient(settings.telegram_bot_token),
        )

    scout_activities = ScoutActivities(
        session_factory,
        registry,
        messenger,
        query_planner=query_planner,
    )
    media_delivery = MediaPreparationDeliveryActivities(
        session_factory,
        messenger,
        media_root=Path(settings.media_root),
    )
    publication_preview = PublicationPreviewActivities(session_factory)
    publication_delivery = PublicationDeliveryActivities(session_factory, messenger)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            PublicationWorkflow,
            ScoutWorkflow,
            MediaPreparationWorkflow,
            DestinationPublicationWorkflow,
        ],
        activities=[
            scout_activities.execute_scout_task,
            scout_activities.deliver_scout_results,
            media_delivery.deliver_media_preparation_result,
            publication_preview.prepare_publication_preview,
            publication_delivery.deliver_publication_result,
        ],
    )
    try:
        await worker.run()
    finally:
        if translation_client is not None:
            await translation_client.aclose()
        if x_connector is not None:
            await x_connector.aclose()
        if messenger is not None:
            await messenger.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
