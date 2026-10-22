import asyncio
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.media.activities import MediaPreparationActivities


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
    activities = MediaPreparationActivities(
        session_factory,
        media_root=Path(settings.media_root),
        max_bytes=settings.media_max_bytes,
    )
    worker = Worker(
        client,
        task_queue=settings.media_task_queue,
        activities=[activities.prepare_candidate_media],
    )
    try:
        await worker.run()
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
