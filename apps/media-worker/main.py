import asyncio
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.media.activities import MediaPreparationActivities
from vimi_social.media.analysis_activities import MediaSceneAnalysisActivities
from vimi_social.media.render_activities import VariantRenderActivities
from vimi_social.media.visual_classifier import (
    OpenAIVisualModerationProvider,
    VisualSceneClassifier,
)


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
    preparation_activities = MediaPreparationActivities(
        session_factory,
        media_root=Path(settings.media_root),
        max_bytes=settings.media_max_bytes,
    )

    visual_classifier: VisualSceneClassifier | None = None
    if settings.openai_api_key:
        visual_classifier = VisualSceneClassifier(
            OpenAIVisualModerationProvider(
                settings.openai_api_key,
                model=settings.visual_moderation_model,
            )
        )
    analysis_activities = MediaSceneAnalysisActivities(
        session_factory,
        media_root=Path(settings.media_root),
        visual_classifier=visual_classifier,
    )
    render_activities = VariantRenderActivities(
        session_factory,
        media_root=Path(settings.media_root),
        max_bytes=settings.media_max_bytes,
    )
    worker = Worker(
        client,
        task_queue=settings.media_task_queue,
        activities=[
            preparation_activities.prepare_candidate_media,
            analysis_activities.analyze_prepared_media,
            render_activities.render_variant,
        ],
    )
    try:
        await worker.run()
    finally:
        if visual_classifier is not None:
            await visual_classifier.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
