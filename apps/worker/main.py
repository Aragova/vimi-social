import asyncio
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.ai.client import LocalAiClient
from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.media.delivery import MediaPreparationDeliveryActivities
from vimi_social.publication.delivery import PublicationDeliveryActivities
from vimi_social.publication.preview import PublicationPreviewActivities
from vimi_social.source.connectors import SourceConnectorRegistry
from vimi_social.source.personalization import (
    PersonalizedFilteringCandidateCurator,
    PersonalizedFilteringScoutContinuationActivities,
    PersonalizedScoutActivities,
)
from vimi_social.source.query_planner import (
    EnglishIntentTranslator,
    FallbackEnglishIntentTranslator,
    MultilingualQueryPlanner,
    OpenAIEnglishIntentTranslator,
)
from vimi_social.source.x_connector import XSourceConnector
from vimi_social.telegram.client import TelegramBotApiClient
from vimi_social.telegram.outgoing import TelegramMessenger, TelegramOutgoingStore
from vimi_social.workflows.destination_publication import DestinationPublicationWorkflow
from vimi_social.workflows.media_preparation import MediaPreparationWorkflow
from vimi_social.workflows.publication import PublicationWorkflow
from vimi_social.workflows.scout import ScoutContinuationWorkflow, ScoutWorkflow


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
        x_connector = XSourceConnector(
            settings.x_bearer_token,
            search_scope=settings.x_search_scope,
        )
        registry.register(x_connector)

    local_ai_client: LocalAiClient | None = None
    translators: list[EnglishIntentTranslator] = []
    if settings.local_ai_url:
        local_ai_client = LocalAiClient(
            settings.local_ai_url,
            timeout_seconds=settings.local_ai_timeout_seconds,
        )
        translators.append(local_ai_client)

    visual_ai_client: LocalAiClient | None = None
    if settings.visual_ai_url:
        visual_ai_client = LocalAiClient(
            settings.visual_ai_url,
            timeout_seconds=settings.visual_ai_timeout_seconds,
        )

    paid_translation_client: OpenAIEnglishIntentTranslator | None = None
    if settings.allow_paid_ai_fallback and settings.search_translation_api_key:
        paid_translation_client = OpenAIEnglishIntentTranslator(
            settings.search_translation_api_key,
            model=settings.search_translation_model,
        )
        translators.append(paid_translation_client)

    if len(translators) > 1:
        translator: EnglishIntentTranslator | None = FallbackEnglishIntentTranslator(
            tuple(translators)
        )
    elif translators:
        translator = translators[0]
    else:
        translator = None
    query_planner = MultilingualQueryPlanner(translator)
    scout_curator = PersonalizedFilteringCandidateCurator()

    messenger: TelegramMessenger | None = None
    if settings.telegram_bot_token:
        messenger = TelegramMessenger(
            TelegramOutgoingStore(session_factory),
            TelegramBotApiClient(settings.telegram_bot_token),
        )

    scout_activities = PersonalizedScoutActivities(
        session_factory,
        registry,
        messenger,
        query_planner=query_planner,
        curator=scout_curator,
        semantic_scorer=local_ai_client,
        visual_scorer=visual_ai_client,
        preview_ocr_extractor=visual_ai_client,
        visual_relevance_weight=settings.visual_relevance_weight,
        preview_ocr_weight=settings.preview_ocr_weight,
        semantic_minimum_relevance=settings.semantic_relevance_min_score,
        retrieval_budget=settings.scout_retrieval_budget,
        retrieval_round_limit=settings.scout_retrieval_round_limit,
        preview_evidence_limit=settings.scout_preview_evidence_limit,
    )
    scout_continuation = PersonalizedFilteringScoutContinuationActivities(
        session_factory,
        registry,
        messenger,
        query_planner=query_planner,
        curator=scout_curator,
        semantic_scorer=local_ai_client,
        semantic_minimum_relevance=settings.semantic_relevance_min_score,
        batch_size=settings.scout_retrieval_round_limit,
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
            ScoutContinuationWorkflow,
            MediaPreparationWorkflow,
            DestinationPublicationWorkflow,
        ],
        activities=[
            scout_activities.execute_scout_task,
            scout_activities.deliver_scout_results,
            scout_continuation.continue_scout_results,
            scout_continuation.deliver_scout_continuation,
            media_delivery.deliver_media_preparation_result,
            publication_preview.prepare_publication_preview,
            publication_delivery.deliver_publication_result,
        ],
    )
    try:
        await worker.run()
    finally:
        if paid_translation_client is not None:
            await paid_translation_client.aclose()
        if visual_ai_client is not None:
            await visual_ai_client.aclose()
        if local_ai_client is not None:
            await local_ai_client.aclose()
        if x_connector is not None:
            await x_connector.aclose()
        if messenger is not None:
            await messenger.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
