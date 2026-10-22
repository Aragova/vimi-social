import asyncio
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker
from temporalio.client import Client
from temporalio.worker import Worker

from vimi_social.core.config import get_settings
from vimi_social.db.base import build_engine
from vimi_social.publication.activities import PublicationActivities


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
    publication_activities = PublicationActivities(
        session_factory,
        media_root=Path(settings.media_root),
    )
    worker = Worker(
        client,
        task_queue=settings.destination_task_queue,
        activities=[
            publication_activities.publish_destination,
            publication_activities.reconcile_destination_publication,
        ],
    )
    try:
        await worker.run()
    finally:
        await publication_activities.aclose()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
